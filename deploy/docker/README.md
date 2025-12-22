# PyPNM Deploy Bundle

This folder is the "install surface" for anyone who wants to run the published PyPNM Docker image without cloning the entire repository.

## What's Included

| Path | Purpose |
|------|---------|
| `compose/docker-compose.yml` | Docker Compose stack that pulls `ghcr.io/svdleer/pypnm:<tag>` and wires up the required volumes. |
| `compose/.env.example` | Default image tag, port binding, and log-level hints. Copy to `.env` (done automatically by `install.sh`). |
| `config/system.json.template` | Canonical PyPNM configuration template. Copy to `config/system.json` and edit for your network. |
| `install.sh` | Helper that copies the template config/.env into place if they do not already exist. |

## Quickstart

1. **Optional – Grab the release bundle**
   - Download `pypnm-deploy-<version>.tar.gz` from the [latest release](https://github.com/svdleer/PyPNM/releases).
   - Extract it somewhere safe (for example `/opt/pypnm`).
2. **Initialize config**

   ```bash
   # From the repo:
   cd /path/to/pypnm/deploy/docker
   ./install.sh
   ```

   Edit `config/system.json` with your SNMP, TFTP/SFTP, and logging details.

3. **Start the stack**

   ```bash
   cd compose
   sudo docker compose pull
   sudo docker compose up -d
   ```

4. **Access the API**
   - Default port: `http://127.0.0.1:8000/docs`
   - Override by editing `compose/.env` before step 3.

5. **Stop / remove (when finished)**

   ```bash
   cd compose
   sudo docker compose down --volumes
   ```

## Notes

- The container reads `config/system.json` at startup. Keep this file outside of version control and back it up as needed.
- Logs/data/output are written to Docker named volumes (`pypnm_logs`, `pypnm_data`, `pypnm_output`). Use `docker volume` commands or `docker compose exec` to inspect them.
- To upgrade to the latest PyPNM image, update `PYPNM_TAG` inside `compose/.env`, then run `docker compose pull && docker compose up -d`.
- Prefer automation? Run `scripts/install-pypnm-docker-container.sh` (from the repo root or via curl). It copies this bundle into `/opt/pypnm` (override with `--deploy-dir`), grabs the latest release by default, seeds `system.json`, and launches the stack automatically.
