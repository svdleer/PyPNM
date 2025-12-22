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
