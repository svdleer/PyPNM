# Generate SSL Certificates

How to create and manage TLS certificates for the PyPNM API.

This page describes recommended patterns for generating TLS certificates for local development and production, how to store them in the PyPNM repo layout, and how to hook them into the FastAPI/uvicorn stack or a reverse proxy.

## Goals

- Enable HTTPS for PyPNM in both development and production.
- Keep private keys out of version control.
- Use short-lived or automatically renewed certificates where possible.
- Provide simple copy-and-paste commands for common environments.

## Terminology

- **Certificate** (`.crt`, `.pem`) - public certificate presented to clients.
- **Private key** (`.key`, `.pem`) - secret key that must be kept private.
- **CA** - Certificate Authority that signs your certificate (public CAs like Let\'s Encrypt, or a local development CA).
- **TLS termination** - where HTTPS is handled (directly in uvicorn or via a reverse proxy such as Nginx or Traefik).

## Recommended Directory Layout

Certificates are not stored in Git. Instead, place them under a local-only directory (for example, `tls/`) that is ignored by `.gitignore`.

Recommended layout at the repo root:

```text
PyPNM/
  tls/
    dev/
      pypnm-dev.key
      pypnm-dev.crt
    prod/
      fullchain.pem
      privkey.pem
```

Add this to `.gitignore` if not already present:

```gitignore
tls/
*.pem
*.key
```

You can adjust names to match your environment; the examples below assume this layout.

## Option 1 - Self-Signed Certificate (Local Development)

For local testing (for example, the [local HTTPS endpoint](https://localhost:8443)), you can use a self-signed certificate.

From the repo root:

```bash
mkdir -p tls/dev

openssl req \
  -x509 -nodes -newkey rsa:4096 \
  -keyout tls/dev/pypnm-dev.key \
  -out tls/dev/pypnm-dev.crt \
  -days 365 \
  -subj "/C=US/ST=CO/L=Highlands Ranch/O=PyPNM/OU=Dev/CN=localhost"
```

Notes:

- This creates a key and certificate valid for 365 days for the host `localhost`.
- Browsers will show a warning because the certificate is not signed by a trusted CA.
- For CLI clients (curl, Python requests) you can typically skip verification during development or point them at `pypnm-dev.crt` as a trusted CA.

## Option 2 - Development Certificates with mkcert

If you want trusted certificates for local development (without browser warnings), consider using [mkcert](https://github.com/FiloSottile/mkcert). mkcert creates a local CA and issues certificates trusted by your machine.

Example (after installing `mkcert`):

```bash
mkdir -p tls/dev

# Create a certificate for localhost and a dev hostname
mkcert -key-file tls/dev/pypnm-dev.key \
       -cert-file tls/dev/pypnm-dev.crt \
       "localhost" "pypnm.local"
```

You can then access PyPNM via the [pypnm.local endpoint](https://pypnm.local:8443) after mapping the hostname in `/etc/hosts`:

```text
127.0.0.1   pypnm.local
```

## Option 3 - Let\'s Encrypt (Production)

For production, use a public CA such as Let\'s Encrypt. The most common tooling is `certbot`.

High-level steps:

1. Ensure DNS for `api.your-domain.example` points to your server.
2. Install `certbot` from your distribution.
3. Request a certificate using either:
   - A standalone mode (certbot runs its own temporary web server), or
   - A webroot / reverse-proxy integration (Nginx, Traefik, etc.).

Example (standalone HTTPS certificate):

```bash
sudo certbot certonly --standalone -d api.your-domain.example
```

Resulting files (paths may vary by distro):

```text
/etc/letsencrypt/live/api.your-domain.example/fullchain.pem
/etc/letsencrypt/live/api.your-domain.example/privkey.pem
```

Configure your reverse proxy or uvicorn to use these paths. Let\'s Encrypt handles renewal (via cron/systemd timers). You typically do **not** copy these into the repository; instead, reference them from their system location.

## Running uvicorn with TLS Directly

For small or internal deployments you can terminate TLS directly in uvicorn.

Example:

```bash
uvicorn pypnm.main:app \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile tls/dev/pypnm-dev.key \
  --ssl-certfile tls/dev/pypnm-dev.crt
```

Or, using production certificates:

```bash
uvicorn pypnm.main:app \
  --host 0.0.0.0 \
  --port 443 \
  --ssl-keyfile /etc/letsencrypt/live/api.your-domain.example/privkey.pem \
  --ssl-certfile /etc/letsencrypt/live/api.your-domain.example/fullchain.pem
```

You can also expose these paths via environment variables and have your launcher script read them:

```bash
export PYPNM_TLS_CERT_FILE=/etc/letsencrypt/live/api.your-domain.example/fullchain.pem
export PYPNM_TLS_KEY_FILE=/etc/letsencrypt/live/api.your-domain.example/privkey.pem
```

Your startup script can then refer to `$PYPNM_TLS_CERT_FILE` and `$PYPNM_TLS_KEY_FILE`.

## Using a Reverse Proxy (Nginx Example)

In many setups, PyPNM runs with plain HTTP on an internal port (for example, 8000), and TLS is terminated by a reverse proxy.

Example Nginx server block:

```nginx
server {
    listen 443 ssl;
    server_name api.your-domain.example;

    ssl_certificate     /etc/letsencrypt/live/api.your-domain.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-domain.example/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host               $host;
        proxy_set_header   X-Real-IP          $remote_addr;
        proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto  https;
    }
}
```

Start uvicorn without TLS behind Nginx:

```bash
uvicorn pypnm.main:app --host 127.0.0.1 --port 8000
```

This pattern keeps TLS configuration in one place and makes certificate renewal easier (only the proxy needs to be reloaded).

## Docker and docker-compose Notes

If you use Docker, mount certificate files into the container as read-only volumes.

Example `docker-compose.yml` snippet (reverse-proxy case):

```yaml
services:
  pypnm-api:
    image: your-registry/pypnm:latest
    environment:
      - PYPNM_ENV=production
    ports:
      - "8000:8000"

  nginx:
    image: nginx:stable
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt/live/api.your-domain.example:/etc/letsencrypt/live/api.your-domain.example:ro
    ports:
      - "443:443"
    depends_on:
      - pypnm-api
```

For a development container with self-signed certs stored under `tls/dev` in the repo:

```yaml
services:
  pypnm-api:
    build: .
    command: >
      uvicorn pypnm.main:app
      --host 0.0.0.0
      --port 8443
      --ssl-keyfile /app/tls/dev/pypnm-dev.key
      --ssl-certfile /app/tls/dev/pypnm-dev.crt
    volumes:
      - ./tls/dev:/app/tls/dev:ro
    ports:
      - "8443:8443"
```

## Renewal and Rotation

- Self-signed or mkcert dev certificates can be regenerated as needed. In practice, 6-12 month lifetimes are common for development.
- Let\'s Encrypt certificates are short-lived (typically 90 days). Ensure `certbot` renewal is scheduled and that your reverse proxy reloads configuration after renewal.
- After key rotation, restart or reload uvicorn or the proxy so the new certificate is in use.

## Security Guidelines

- Never commit private keys (`.key`, `.pem`) to Git.
- Restrict file permissions on key files (for example, `chmod 600` for private keys).
- For production, prefer a reverse proxy plus Let\'s Encrypt (or another public CA) over long-lived self-signed certificates.
- If you need mutual TLS (client certificates), extend your proxy configuration to validate client certificates and pass identity to PyPNM via headers.
