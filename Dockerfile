# syntax=docker/dockerfile:1.6
FROM ubuntu:24.04

ARG http_proxy
ARG https_proxy
ARG no_proxy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    http_proxy=${http_proxy} \
    https_proxy=${https_proxy} \
    no_proxy=${no_proxy} \
    HTTP_PROXY=${http_proxy} \
    HTTPS_PROXY=${http_proxy} \
    NO_PROXY=${no_proxy}

WORKDIR /app

# Use HTTPS for Ubuntu repos (archive + security)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      gosu \
      iputils-ping \
      wget \
      python3.12 \
      python3-pip \
      python3.12-venv \
 && rm -rf /var/lib/apt/lists/*

# Create a venv to avoid PEP 668 / externally-managed-environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3.12 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Optional: pip proxy config (only if you actually pass http_proxy)
RUN if [ -n "${http_proxy}" ]; then pip config set global.proxy "${http_proxy}"; fi

COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
COPY demo/ /app/demo/
COPY deploy/docker/config/ /app/deploy/config/
COPY tools/ /app/tools/
COPY mibs/ /app/mibs/
COPY docker/entrypoint.sh /app/entrypoint.sh

# Ensure settings/system.json exists before pip install bundles the package.
# Falls back to the template if the file was accidentally deleted from the repo.
RUN mkdir -p /app/src/pypnm/settings \
 ; [ -f /app/src/pypnm/settings/system.json ] \
    || cp /app/deploy/config/system.json.template /app/src/pypnm/settings/system.json

# Install your package into the venv (no --break-system-packages)
RUN pip install --upgrade pip \
 && pip install . \
 && pip install pysnmp-mibs \
 && useradd -m -u 10001 -s /usr/sbin/nologin pypnm \
 && chmod +x /app/entrypoint.sh \
 && if [ -f /app/deploy/config/system.json.template ] && [ ! -f /app/deploy/config/system.json ]; then \
      cp /app/deploy/config/system.json.template /app/deploy/config/system.json; \
    fi \
 && chown -R pypnm:pypnm /home/pypnm

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3.12", "-m", "uvicorn", "pypnm.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
