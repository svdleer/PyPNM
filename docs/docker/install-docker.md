# Install Docker Prerequisites (Ubuntu 22.04/24.04)

These steps install Docker Engine, the Compose plugin, and supporting packages for PyPNM’s container workflow.
For broader Linux/macOS installation guidance, see the [official Docker Engine docs](https://docs.docker.com/engine/install/).

## Install flow (script-only, recommended)

Use the helper script on Ubuntu 22.04/24.04 without cloning the repo:

```bash
curl -fsSL https://raw.githubusercontent.com/svdleer/PyPNM/main/tools/docker/install-docker-ubuntu.sh \\
  -o /tmp/install-docker-ubuntu.sh
bash /tmp/install-docker-ubuntu.sh
```

Repo clone path (if you cloned the repo):

```bash
tools/docker/install-docker-ubuntu.sh
```

Optional (non-production): allow your user to run `docker` without `sudo`.

```bash
sudo groupadd docker || true
sudo usermod -aG docker "$USER"
echo "Log out and back in for group changes to apply."
```

Uninstall (optional):

```bash
bash /tmp/install-docker-ubuntu.sh --uninstall
```

Once Docker is available, return to the [PyPNM Docker install guide](install.md) or run the helper script from the README.
