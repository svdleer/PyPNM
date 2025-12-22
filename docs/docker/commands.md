# PyPNM Docker Commands Cheat Sheet

Common commands for administering the PyPNM Docker deployment on a host/VM.

## Table Of Contents

- [Working Directory](#working-directory)
- [Stack Lifecycle](#stack-lifecycle)
- [Developer Workflow](#developer-workflow)
- [Images And Updates](#images-and-updates)
- [Config Menu](#config-menu)
- [Logs And Health](#logs-and-health)
- [Inspect And Debug](#inspect-and-debug)
- [Cleanup](#cleanup)
- [Networking Notes](#networking-notes)

## Working Directory

All commands below assume:

```bash
cd /opt/pypnm/compose
```

Tip: verify what services exist in your compose bundle:

```bash
sudo docker compose config --services
```

## Stack Lifecycle

Start the stack:

```bash
sudo docker compose up -d
```

Stop the stack:

```bash
sudo docker compose down
```

Stop the stack and remove named volumes (deletes stored logs/output/data in volumes):

```bash
sudo docker compose down --volumes
```

Restart only the API service:

```bash
sudo docker compose restart pypnm-api
```

Recreate containers (useful after changing the image tag or ports):

```bash
sudo docker compose up -d --force-recreate
```

## Developer Workflow

Local development relies on the same compose services, just executed from your cloned repository:

1. Clone the repo and run the installer:

   ```bash
   git clone https://github.com/svdleer/PyPNM.git
   cd PyPNM
   ./install.sh
   ```

2. Build/test locally via `docker-compose.yml` helpers:

   ```bash
   make docker-up      # docker compose up -d --build
   make docker-logs    # follow API logs
   make docker-down    # stop + remove volumes
   ```

3. Use the Python tooling (`pytest`, `ruff`, etc.) inside `.env/` for day-to-day development.

## Images And Updates

Pull the image tag referenced by your `.env` (or `docker-compose.yml`):

```bash
sudo docker compose pull
```

Show current images in use:

```bash
sudo docker compose images
```

Show container status (compose services only):

```bash
sudo docker compose ps
```

## Config Menu

If your compose file includes a `config-menu` service, run it interactively:

```bash
sudo docker compose run --rm -it config-menu
```

If `config-menu` is not listed in `docker compose config --services`, it is not available in the deployed bundle.

Reload the API without a container restart (only if your API exposes this endpoint):

```bash
curl -X GET "http://127.0.0.1:${HOST_PORT:-8080}/pypnm/system/webService/reload" -H "accept: application/json"
```

## Logs And Health

Tail API logs:

```bash
sudo docker compose logs -f --tail=200 pypnm-api
```

Follow all logs for the API service (no tail limit):

```bash
sudo docker compose logs -f pypnm-api
```

Quick docs endpoint health check:

```bash
curl -I "http://127.0.0.1:${HOST_PORT:-8080}/docs"
```

Wait for container health to turn healthy:

```bash
watch -n 1 "sudo docker ps --format 'table {{.Names}}	{{.Status}}	{{.Ports}}' | sed -n '1p;/pypnm-api/p'"
```

## Inspect And Debug

Open a shell in the running API container:

```bash
sudo docker exec -it pypnm-api sh
```

List containers (running only):

```bash
sudo docker ps
```

List containers (all, including stopped):

```bash
sudo docker ps -a
```

List container names only (useful for scripting):

```bash
sudo docker ps -a --format "{{.Names}}"
```

Show effective compose configuration (after env var expansion):

```bash
sudo docker compose config
```

Inspect the container (networking, mounts, env):

```bash
sudo docker inspect pypnm-api
```

Test network reachability from inside the container (HTTP example):

```bash
sudo docker exec -it pypnm-api sh -lc "python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/docs").read(); print("OK")'"
```

If `ping` is available in the image, you can also do:

```bash
sudo docker exec -it pypnm-api ping -c 1 <target-ip>
```

## Cleanup

Remove a specific container:

```bash
sudo docker rm -f <container>
```

Remove all stopped containers only:

```bash
sudo docker container prune -f
```

Remove all containers (running and stopped). This is destructive:

```bash
sudo docker rm -f $(sudo docker ps -aq)
```

Examples: targeted cleanup without touching other projects:

List containers and find old PyPNM instances:

```bash
sudo docker ps -a --format "table {{.Names}}	{{.Image}}	{{.Status}}" | grep -i pypnm
```

Remove only containers whose names start with `pypnm`:

```bash
sudo docker rm -f $(sudo docker ps -a --format "{{.Names}}" | grep '^pypnm')
```

Remove only containers created from a specific image tag:

```bash
sudo docker rm -f $(sudo docker ps -a --filter "ancestor=ghcr.io/svdleer/PyPNM:v0.9.48.0" -q)
```

Remove unused images (dangling):

```bash
sudo docker image prune -f
```

Remove unused images (all unreferenced by any container):

```bash
sudo docker image prune -a -f
```

Prune unused resources (stopped containers, dangling images, unused networks):

```bash
sudo docker system prune -f
```

Aggressive prune (also removes unused images and volumes):

```bash
sudo docker system prune -a --volumes -f
```

List Docker volumes:

```bash
sudo docker volume ls
```

Remove a specific volume:

```bash
sudo docker volume rm <volume>
```

Remove all unused volumes:

```bash
sudo docker volume prune -f
```

## Networking Notes

If the API must share host routes directly (for example, to reach modems on local LAN subnets with strict ACLs),
configure host networking for the API service and recreate the stack.

1) Edit `/opt/pypnm/compose/docker-compose.yml` and set under `pypnm-api`:

```yaml
network_mode: host
```

2) Recreate:

```bash
cd /opt/pypnm/compose
sudo docker compose down
sudo docker compose up -d
```

When `network_mode: host` is enabled, published `ports:` mappings are ignored because the container shares the host network.
