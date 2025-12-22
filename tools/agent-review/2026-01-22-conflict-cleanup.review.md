## Agent Review Bundle Summary
- Goal: Resolve merge conflict markers across repo docs/config and restore valid pyproject formatting.
- Changes: Remove conflict markers; keep single TAG/version lines; update SPDX year in version file.
- Files: README.md; docs/docker/install.md; docs/kubernetes/commands.md; docs/kubernetes/kind-freelens.md; docs/kubernetes/kind-install.md; docs/kubernetes/multi-cluster-kind.md; docs/kubernetes/pypnm-deploy.md; docs/kubernetes/quickstart.md; docs/kubernetes/scale-replicas-kind.md; docs/kubernetes/ten-instances-kind.md; pyproject.toml; src/pypnm/version.py
- Tests: python3 -m compileall src; ruff check src (fails: pre-existing import/order/undefined issues); ruff format --check . (fails: many files would reformat); pytest -q (passed, 510 passed, 3 skipped: PNM_CM_IT)
- Notes: Ruff failures appear pre-existing; no code behavior changes intended.

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

[![PyPNM Version](https://img.shields.io/github/v/tag/svdleer/PyPNM?label=PyPNM&sort=semver)](https://github.com/svdleer/PyPNM/tags)
[![PyPI - Version](https://img.shields.io/pypi/v/pypnm-docsis.svg)](https://pypi.org/project/pypnm-docsis/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pypnm-docsis.svg)](https://pypi.org/project/pypnm-docsis/)
[![Daily Build](https://github.com/svdleer/PyPNM/actions/workflows/daily-build.yml/badge.svg?branch=main)](https://github.com/svdleer/PyPNM/actions/workflows/daily-build.yml)
![CodeQL](https://github.com/svdleer/PyPNM/actions/workflows/codeql.yml/badge.svg)
[![PyPI Install Check](https://github.com/svdleer/PyPNM/actions/workflows/pypi-install-check.yml/badge.svg?branch=main)](https://github.com/svdleer/PyPNM/actions/workflows/pypi-install-check.yml)
[![Kubernetes (kind)](https://github.com/svdleer/PyPNM/actions/workflows/kubernetes-kind.yml/badge.svg?branch=main)](https://github.com/svdleer/PyPNM/actions/workflows/kubernetes-kind.yml)
[![GHCR Publish](https://github.com/svdleer/PyPNM/actions/workflows/publish-ghcr.yml/badge.svg)](https://github.com/svdleer/PyPNM/actions/workflows/publish-ghcr.yml)
[![Dockerized](https://img.shields.io/badge/GHCR-latest-2496ED?logo=docker&logoColor=white&label=Docker)](https://github.com/svdleer/PyPNM/pkgs/container/pypnm)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%20%7C%2024.04%20LTS-E95420?logo=ubuntu&logoColor=white)](https://github.com/svdleer/PyPNM)

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
TAG="v1.0.29.0"
PORT=8080

curl -fsSLo install-pypnm-docker-container.sh \
  https://raw.githubusercontent.com/svdleer/PyPNM/main/scripts/install-pypnm-docker-container.sh

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
  pip install pypnm-docsis
  ```

Uninstall and cleanup:

  ```bash
  pip uninstall pypnm-docsis
  rm -f ~/.ssh/pypnm_secrets.key
  ```

For full FastAPI service usage and development, use the repository-based flow below.

### 1) Clone

  ```bash
  git clone https://github.com/svdleer/PyPNM.git
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

System configuration lives in [deploy/docker/config/system.json](https://github.com/svdleer/PyPNM/blob/main/deploy/docker/config/system.json).

- [Config menu](docs/system/menu.md): `source ~/.bashrc && config-menu`
- [System Configuration Reference](docs/system/system-config.md): field-by-field descriptions and defaults
If you installed with `--pnm-file-retrieval-setup`, it runs automatically and backs up `system.json` first.

<!-- Removed duplicated Step 3/4 block -->

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

# FILE: docs/docker/install.md
# PyPNM Docker Install & Usage

PyPNM ships with Docker assets so you can run the API quickly on a workstation, lab host, or VM. This guide covers the common flows:

- Install the published release image via the helper script.
- Use the deploy bundle (tarball) directly.
- Manual steps for hosts without GitHub access.

## Table of Contents

- [Fast path (helper script)](#fast-path-helper-script)
- [Deploy bundle flow (tarball)](#deploy-bundle-flow-tarball)
- [Manual/no-network notes](#manualno-network-notes)

## Fast path: PyPNM Docker container install

```bash
TAG="v1.0.29.0"
PORT=8080

curl -fsSLo install-pypnm-docker-container.sh \
  https://raw.githubusercontent.com/svdleer/PyPNM/main/scripts/install-pypnm-docker-container.sh

chmod +x install-pypnm-docker-container.sh

sudo ./install-pypnm-docker-container.sh --tag ${TAG} --port ${PORT}
```

What the script does:

- Downloads the deploy bundle (falls back to tag source if the asset is missing).
- Seeds `deploy/docker/config/system.json` and `deploy/docker/compose/.env`.
- Pulls `ghcr.io/svdleer/PyPNM:${TAG}` and starts the stack in `/opt/pypnm/compose`.
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
TAG="v1.0.29.0"
WORKING_DIR="PyPNM-${TAG}"

mkdir -p "${WORKING_DIR}"
cd "${WORKING_DIR}"

wget "https://github.com/svdleer/PyPNM/archive/refs/tags/${TAG}.tar.gz"
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

# FILE: docs/kubernetes/commands.md
# Kubernetes (kind) commands

## Table of contents

- [Cluster lifecycle](#cluster-lifecycle)
- [Context and nodes](#context-and-nodes)
- [Apply and inspect](#apply-and-inspect)
- [Rollout and health](#rollout-and-health)
- [Images](#images)
- [Script-only deploy (no repo clone)](#script-only-deploy-no-repo-clone)
- [Cleanup](#cleanup)
- [Scaling and multiple instances](#scaling-and-multiple-instances)
- [Full teardown](#full-teardown)

Common commands for local kind-based testing.

## Cluster lifecycle

Create, list, and delete kind clusters.

```bash
kind create cluster --name pypnm-dev
kind get clusters
kind delete cluster --name pypnm-dev
```

## Context and nodes

Switch contexts and verify node readiness.

```bash
kubectl config get-contexts
kubectl config use-context kind-pypnm-dev
kubectl get nodes -o wide
```

## Apply and inspect

Apply manifests and inspect pod status/logs.

```bash
kubectl apply -k deploy/kubernetes
kubectl get pods -o wide
kubectl describe pod -l app=pypnm-api
kubectl logs -l app=pypnm-api --tail=200
```

## Rollout and health

Wait for rollout and validate the health endpoint.

```bash
kubectl rollout status deploy/pypnm-api --timeout=120s
kubectl port-forward deploy/pypnm-api 8000:8000
curl -i http://127.0.0.1:8000/health
```

## Images

Build a local image, load into kind, and restart the deployment.

```bash
docker build -t pypnm:local --build-arg PYTHON_VERSION=3.12 .
kind load docker-image pypnm:local --name pypnm-dev
kubectl set image deploy/pypnm-api pypnm-api=pypnm:local
kubectl rollout restart deploy/pypnm-api
```

## Script-only deploy (no repo clone)

Deploy from GHCR using a remote manifest (no repo clone required):

```bash
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh

TAG="v1.0.29.0"
NAMESPACE="pypnm-cmts-a"

bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
```

Teardown:

```bash
bash /tmp/pypnm_k8s_remote_deploy.sh --teardown --namespace "${NAMESPACE}"
```

## Cleanup

Remove the deployment and related resources.

```bash
kubectl delete -k deploy/kubernetes
```

## Scaling and multiple instances

Scale replicas or create a second kind cluster.

```bash
kubectl scale deploy/pypnm-api --replicas=3
kubectl get pods -o wide
```

Use a different kind cluster name for multiple isolated instances:

```bash
kind create cluster --name pypnm-dev-2
kubectl config use-context kind-pypnm-dev-2
kubectl apply -k deploy/kubernetes
```

## Full teardown

Delete resources and remove the cluster.

```bash
kubectl delete -k deploy/kubernetes
kind delete cluster --name pypnm-dev
```

# FILE: docs/kubernetes/kind-freelens.md
# kind + FreeLens on a VM (GHCR)

This guide documents a VM-friendly workflow for running PyPNM on kind and managing it in FreeLens. The model below assumes **one PyPNM service per CMTS**, with multiple namespaces living on a single VM/cluster.

## Prerequisites

- VM with Docker installed and running.
- `curl` and `sudo` available.
- Network access to GHCR (`ghcr.io/svdleer/PyPNM`).

## Install kubectl + kind

Use the bootstrap helper for Debian/Ubuntu-style hosts (no repo clone required):

```bash
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_kind_vm_bootstrap.sh \
  -o /tmp/pypnm_kind_vm_bootstrap.sh
bash /tmp/pypnm_kind_vm_bootstrap.sh
```

## Create the cluster and deploy from GHCR

Pick a release tag, then deploy into a namespace (one namespace per CMTS). This script pulls manifests from GitHub, so no repo clone is required:

```bash
TAG="v1.0.29.0"
NAMESPACE="pypnm-cmts-a"

curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh
bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
```

Health check:

```bash
kubectl port-forward --namespace "${NAMESPACE}" deploy/pypnm-api 8000:8000
curl -i http://127.0.0.1:8000/health
```

If the returned `version` is older than expected, verify the tag used in the deploy command and confirm the namespace matches the running deployment.

## Connect with FreeLens

1. Add the kubeconfig from the VM to FreeLens.
   - If FreeLens runs on the VM, it can use `~/.kube/config` directly.
   - If FreeLens runs on your workstation, copy the kubeconfig from the VM:

     ```bash
     VM_USER="dev01"
     VM_HOST="10.0.0.10"
     LOCAL_KUBECONFIG="${HOME}/.kube/pypnm-dev-kubeconfig"

     scp ${VM_USER}@${VM_HOST}:~/.kube/config "${LOCAL_KUBECONFIG}"
     ```

     PowerShell:

     ```powershell
     $VM_USER = "dev01"
     $VM_HOST = "10.0.0.10"
     $LOCAL_KUBECONFIG_DIR = "$env:USERPROFILE\\.kube"
     $LOCAL_KUBECONFIG = "$LOCAL_KUBECONFIG_DIR\\pypnm-dev-kubeconfig"

     New-Item -ItemType Directory -Force -Path $LOCAL_KUBECONFIG_DIR | Out-Null
     scp ${VM_USER}@${VM_HOST}:~/.kube/config "$LOCAL_KUBECONFIG"
     ```

   - In FreeLens: **Catalog → Clusters → Add Cluster → From kubeconfig**, then select the copied file.
   - If FreeLens runs on Windows, update any file paths inside the kubeconfig (for example, replace `/home/dev01/...` with `C:\\Users\\<you>\\...`).
     Then use an SSH tunnel for the API port:

     ```bash
     VM_USER="dev01"
     VM_HOST="10.0.0.10"
     VM_PORT="8000"

     ssh -L ${VM_PORT}:127.0.0.1:${VM_PORT} ${VM_USER}@${VM_HOST}
     ```

     PowerShell:

     ```powershell
     $VM_USER = "dev01"
     $VM_HOST = "10.0.0.10"
     $VM_PORT = "8000"

     ssh -L ${VM_PORT}:127.0.0.1:${VM_PORT} ${VM_USER}@${VM_HOST}
     ```
2. Select the target namespace (`pypnm-cmts-a`).
   - In FreeLens 1.7.0: open **Catalog** (top-left icon), choose **Clusters**, then switch the namespace selector in the top bar to `pypnm-cmts-a`.
3. In FreeLens, open the target namespace and locate `pypnm-api` (Service or Pod).
4. Start a port-forward for `pypnm-api` to local port 8000.
   - Service: forward `8000 -> 8000`.
   - Pod: forward `8000 -> 8000`.
5. Open `http://127.0.0.1:8000/health` in your browser.
   - If you are tunneling, keep the SSH tunnel running and use the same `http://127.0.0.1:8000` URL on Windows.

Tip: keep one FreeLens workspace per CMTS namespace so it is easy to keep sessions isolated.

## Deployment examples

| Example | When to use |
| --- | --- |
| [Single namespace with 10 replicas](scale-replicas-kind.md) | Load testing or simple HA with one endpoint. |
| [10 namespaces, 10 ports](ten-instances-kind.md) | One instance per CMTS or per customer. |
| [Multiple kind clusters](multi-cluster-kind.md) | Hard isolation between environments. |

## One VM, multiple CMTS (one PyPNM per CMTS)

Deploy a PyPNM instance per CMTS by assigning a unique namespace and configuration per CMTS:

```bash
TAG="v1.0.29.0"

for CMTS in cmts-a cmts-b cmts-c; do
  NAMESPACE="pypnm-${CMTS}"
  bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
done
```

### CMTS-specific config

Each instance should point at exactly one CMTS. Use a per-namespace config patch and apply it as described in [PyPNM on Kubernetes (kind)](pypnm-deploy.md) ("Config overrides" section). Keep the CMTS routing and retrieval settings unique per namespace.

## Teardown

```bash
NAMESPACE="pypnm-cmts-a"

bash /tmp/pypnm_k8s_remote_deploy.sh --teardown --namespace "${NAMESPACE}"
```

To delete the cluster after all namespaces are removed:

```bash
kind delete cluster --name pypnm-dev
```

# FILE: docs/kubernetes/kind-install.md
# Local Kubernetes (kind) install

Use this for lightweight local Kubernetes testing on a Docker-enabled host. For deeper configuration options, refer to the [official kind site](https://kind.sigs.k8s.io/).

Docker is required to run kind. If it is not installed yet, follow the [Docker install guide](../docker/install-docker.md) first.

## Install kubectl + kind (Debian/Ubuntu)

Follow this flow:

1) Install Docker first: [Docker install guide](../docker/install-docker.md).
2) Run the bootstrap script to install `kubectl` + `kind`.

```bash
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_kind_vm_bootstrap.sh \
  -o /tmp/pypnm_kind_vm_bootstrap.sh
bash /tmp/pypnm_kind_vm_bootstrap.sh
```

## Create a local cluster

```bash
kind create cluster --name pypnm-dev
kubectl get nodes
```

## Script-only deploy (no repo clone)

```bash
TAG="v1.0.29.0"
NAMESPACE="pypnm-cmts-a"
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh
bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
```

Next step: deploy PyPNM from GHCR using [PyPNM on Kubernetes (kind)](pypnm-deploy.md).

## Delete the cluster

```bash
kind delete cluster --name pypnm-dev
```

# FILE: docs/kubernetes/multi-cluster-kind.md
# Multiple kind clusters (hard isolation)

This scenario runs separate kind clusters on the same VM for strong isolation.
Each cluster has its own kubeconfig context and its own PyPNM deployment.

## Create clusters

```bash
CLUSTER_A="pypnm-dev-a"
CLUSTER_B="pypnm-dev-b"

kind create cluster --name "${CLUSTER_A}"
kind create cluster --name "${CLUSTER_B}"
```

## Deploy to each cluster

```bash
TAG="v1.0.29.0"
NAMESPACE="pypnm-default"

kubectl config use-context kind-pypnm-dev-a
kubectl create namespace "${NAMESPACE}" || true
kubectl config set-context --current --namespace="${NAMESPACE}"
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh
bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1

kubectl config use-context kind-pypnm-dev-b
kubectl create namespace "${NAMESPACE}" || true
kubectl config set-context --current --namespace="${NAMESPACE}"
bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas 1
```

## Port-forward each cluster

```bash
kubectl config use-context kind-pypnm-dev-a
kubectl -n pypnm-default port-forward deploy/pypnm-api 8100:8000

kubectl config use-context kind-pypnm-dev-b
kubectl -n pypnm-default port-forward deploy/pypnm-api 8101:8000
```

# FILE: docs/kubernetes/pypnm-deploy.md
# PyPNM on Kubernetes (kind)

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
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \\
  -o /tmp/pypnm_k8s_remote_deploy.sh
TAG="v1.0.29.0"
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

# FILE: docs/kubernetes/quickstart.md
# Kubernetes quickstart (kind)

Copy-paste flow using the current release tag:

```bash
TAG="v1.0.29.0"
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag ${TAG} --replicas 1
```

To target a specific namespace (useful for one PyPNM per CMTS):

```bash
TAG="v1.0.29.0"
NAMESPACE="pypnm-cmts-a"
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag ${TAG} --replicas 1 --namespace ${NAMESPACE}
```

To use a local image:

```bash
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source local --replicas 1
```

Script-only deploy (no repo clone) is covered in [PyPNM on Kubernetes (kind)](pypnm-deploy.md).

# FILE: docs/kubernetes/scale-replicas-kind.md
# Single namespace with 10 replicas (one port)

This scenario scales a single PyPNM deployment to 10 replicas behind one Service.
Use it for throughput testing or simple HA without per-namespace isolation.

## Deploy (or update) and scale

```bash
TAG="v1.0.29.0"
NAMESPACE="pypnm-default"
REPLICAS="10"

curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh

bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas ${REPLICAS}
```

## Port-forward (single port)

```bash
NAMESPACE="pypnm-default"
LOCAL_PORT="8100"

kubectl -n "${NAMESPACE}" port-forward deploy/pypnm-api ${LOCAL_PORT}:8000
```

## Verify

```bash
LOCAL_PORT="8100"
curl -i http://127.0.0.1:${LOCAL_PORT}/health
```

# FILE: docs/kubernetes/ten-instances-kind.md
# 10 PyPNM instances on one kind cluster (ports 8100–8109)

This scenario runs 10 isolated PyPNM instances (one per namespace) on a single VM
and exposes each instance on a unique local port.

## Diagram

![10 PyPNM instances on one kind cluster](../images/kubernetes/ten-instances-kind.svg)

## Deploy 10 namespaces (parallel)

```bash
TAG="v1.0.29.0"
BASE_NS="pypnm-cmts"
REPLICAS="1"
COUNT="10"

export KUBECONFIG="${HOME}/.kube/config"
if ! kind get clusters | grep -q "^pypnm-dev$"; then
  kind create cluster --name pypnm-dev
fi
kubectl config use-context kind-pypnm-dev

curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/k8s/pypnm_k8s_remote_deploy.sh \
  -o /tmp/pypnm_k8s_remote_deploy.sh

for i in $(seq 0 $((COUNT - 1))); do
  NAMESPACE="${BASE_NS}-${i}"
  bash /tmp/pypnm_k8s_remote_deploy.sh --create --tag "${TAG}" --namespace "${NAMESPACE}" --replicas ${REPLICAS} &
done
wait
```

## Start port-forwards (8100–8109)

```bash
BASE_PORT="8100"
BASE_NS="pypnm-cmts"
COUNT="10"
LOG_DIR="/tmp/pypnm-portforward"

mkdir -p "${LOG_DIR}"

for i in $(seq 0 $((COUNT - 1))); do
  NAMESPACE="${BASE_NS}-${i}"
  PORT=$((BASE_PORT + i))
  kubectl -n "${NAMESPACE}" port-forward deploy/pypnm-api ${PORT}:8000 \
    >"${LOG_DIR}/${NAMESPACE}.log" 2>&1 &
  echo $! >> "${LOG_DIR}/pids.txt"
done
```

## Verify

```bash
BASE_PORT="8100"
COUNT="10"

for i in $(seq 0 $((COUNT - 1))); do
  PORT=$((BASE_PORT + i))
  STATUS="$(curl -s http://127.0.0.1:${PORT}/health | sed -n 's/.*"status":"\\([^"]*\\)".*/\\1/p')"
  [ -z "${STATUS}" ] && STATUS="ok"
  echo "127.0.0.1:${PORT} -> ${STATUS}"
done
```

## Cleanup

```bash
BASE_NS="pypnm-cmts"
COUNT="10"
LOG_DIR="/tmp/pypnm-portforward"

if [ -f "${LOG_DIR}/pids.txt" ]; then
  xargs -r kill < "${LOG_DIR}/pids.txt"
  rm -f "${LOG_DIR}/pids.txt"
fi

for i in $(seq 0 $((COUNT - 1))); do
  NAMESPACE="${BASE_NS}-${i}"
  bash /tmp/pypnm_k8s_remote_deploy.sh --teardown --namespace "${NAMESPACE}"
done

kind delete cluster --name pypnm-dev
```

# FILE: pyproject.toml
# SPDX-License-Identifier: Apache-2.0

[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name            = "pypnm-docsis"
version         = "1.0.29.0"
description     = "DOCSIS 3.x/4.0 Proactive Network Maintenance Toolkit"
readme          = "README.md"
requires-python = ">=3.10"
license         = "Apache-2.0"

authors = [
  { name = "Maurice Garcia", email = "mgarcia01752@outlook.com" }
]

classifiers = [
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3 :: Only",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Operating System :: OS Independent",
  "Framework :: FastAPI",
  "Topic :: System :: Networking",
  "Typing :: Typed",
]

license-files = ["LICENSE", "NOTICE"]

dependencies = [
  "fastapi==0.115.12",
  "uvicorn[standard]==0.34.2",
  "python-multipart>=0.0.20",
  "numpy==2.2.6",
  "scipy==1.15.1",
  "pydantic>=2.12.4,<2.13",
  "pysmi==1.6.1",
  "pysnmp==7.1.17",
  "python-dotenv>=1.0.0",
  "requests==2.32.3",
  "pandas==2.2.3",
  "paramiko==3.5.1",
  "tftpy==0.8.5",
  "matplotlib==3.10.8",
  "typing-extensions>=4.10.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0.0",
  "pytest-cov>=5.0.0",
  "pytest-asyncio>=0.23.5",
  "black>=24.0.0",
  "pydantic-settings>=2.6.0",
  "ruff>=0.14.7",
  "pycycle>=0.0.8",
  "pyright>=1.1.407",
  "pyyaml>=6.0.2",
]
docs = [
  "mkdocs>=1.6",
  "mkdocs-material>=9.5",
  "pymdown-extensions>=10.8",
]
reports = []

[project.urls]
Homepage    = "https://www.pypnm.io"
Repository  = "https://github.com/svdleer/PyPNM"
Bug-Tracker = "https://github.com/svdleer/PyPNM/issues"
Documentation = "https://www.pypnm.io"

[project.scripts]
pypnm      = "pypnm.cli:main"
docs-serve = "mkdocs.__main__:serve"
docs-build = "mkdocs.__main__:build"
pypnm-software-qa-checker  = "pypnm.tools.qa_checker:main"

[tool.setuptools]
package-dir = { "" = "src" }
include-package-data = true

[tool.setuptools.packages.find]
where   = ["src"]
include = ["pypnm*"]

[tool.setuptools.package-data]
"pypnm" = [
  "settings/*.json",
  "py.typed",
]

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
filterwarnings = [
  "ignore:getReadersFromUrls is deprecated:DeprecationWarning:pysnmp",
  "ignore:smiV1Relaxed is deprecated:DeprecationWarning:pysnmp",
  "ignore:.*getReadersFromUrls.*:DeprecationWarning:pysmi.reader.url",
  "ignore:.*addSources.*:DeprecationWarning:pysnmp.smi.compiler",
  "ignore:.*addSearchers.*:DeprecationWarning:pysnmp.smi.compiler",
  "ignore:.*addBorrowers.*:DeprecationWarning:pysnmp.smi.compiler",
]

[tool.coverage.run]
branch = true
source = ["pypnm"]

[tool.coverage.report]
show_missing = true
skip_covered = true

[tool.black]
line-length = 100
target-version = ["py310"]

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
# Common, high-signal rulesets:
# F   = Pyflakes (real errors)
# E,W = pycodestyle
# I   = import sorting
# B   = flake8-bugbear
# UP  = pyupgrade
#
# Ignore:
# E501 - https://docs.astral.sh/ruff/rules/line-too-long/
# B006 - https://docs.astral.sh/ruff/rules/mutable-argument-default/
#
# ---------------------------------------------------------------------------
# Ruff Roadmap (do NOT enable by default; turn on gradually when ready)
# ---------------------------------------------------------------------------
# Phase 1 (current):
#   - Focus on correctness + core style only.
#   - Enabled rule families:
#       F, E, W, I, B, UP
#
# Phase 2 (optional): Naming rules
#   - Add N (pep8-naming) when public API naming is stable.
#   - This enforces conventional names for functions, classes, etc.
#   - Example change (for later, DO NOT UNCOMMENT YET):
#       select = ["F", "E", "W", "I", "B", "UP", "N"]
#
# Phase 3 (optional): Type-annotation rules
#   - Add ANN to enforce more consistent type hints once F/E/W noise is low.
#   - You can selectively ignore strict ANN codes if needed (e.g., ANN101/ANN102).
#   - Example (for later):
#       select = ["F", "E", "W", "I", "B", "UP", "ANN"]
#       ignore = ["E501", "B006", "ANN101", "ANN102"]
#
# Phase 4 (optional): Simplification & performance hints
#   - Enable SIM (flake8-simplify) to flag redundant or over-complicated logic.
#   - Enable PERF to catch obvious performance footguns in hot paths.
#   - Recommended approach:
#       - First, run ad-hoc from CLI without adding to select:
#           ruff check src --select SIM,PERF
#       - Fix only the diagnostics you agree with.
#   - If you like the results, you can later extend select:
#       select = ["F", "E", "W", "I", "B", "UP", "N", "ANN", "SIM", "PERF"]
#
# Packs to generally avoid for PyPNM (unless explicitly desired later):
#   - D (pydocstyle): conflicts with custom docstring rules.
#   - C90 / PL (mccabe / pylint families): very noisy, low signal for this project.

select = ["F", "E", "W", "I", "B", "UP", "ANN", "SIM", "PERF"]
ignore = [
  "E501",
  "B006"
]

[tool.pyright]
pythonVersion = "3.10"
pythonPlatform = "Linux"

include = ["src"]
exclude = [
  "tools",
  "src/pypnm/examples/",
  "**/__pycache__",
]

# VSCode + .env venv
venvPath = "."
venv = ".env"

reportMissingImports = "warning"
reportMissingTypeStubs = "warning"
typeCheckingMode = "basic"

# FILE: src/pypnm/version.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025-2026 Maurice Garcia

from __future__ import annotations

__all__ = ["__version__"]

# MAJOR.MINOR.MAINTENANCE.BUILD
__version__: str = "1.0.29.0"
