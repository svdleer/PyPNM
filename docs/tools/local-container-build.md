# Local Container Preflight (`tools/local/local_container_build.sh`)

Use this helper to validate the Docker images locally before cutting a release.

## Usage

- Build images only:

```bash
./tools/local/local_container_build.sh
```

- Build + smoke test (start compose, wait for `pypnm-api` health, then tear down):

```bash
./tools/local/local_container_build.sh --smoke
```

## Requirements

- Docker Engine with buildx and the docker compose plugin (on Debian/Ubuntu you can install `docker.io docker-buildx-plugin docker-compose-plugin`, or use the official Docker CE repo). See [Install Docker prerequisites](../docker/install-docker.md) if Docker is not set up yet.
- Daemon access (run with `sudo` or add your user to the `docker` group if needed).
  - If buildx is missing, Docker falls back to the legacy builder and emits a deprecation warning during image builds.

## What it does

1. Builds compose images (`docker compose --progress plain build`).
2. If `--smoke` is set, brings up the stack, waits for `pypnm-api` to become healthy, then tears down (`docker compose down --volumes`).
