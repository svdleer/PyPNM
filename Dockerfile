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
    HTTPS_PROXY=${https_proxy} \
    NO_PROXY=${no_proxy}

WORKDIR /app

# Install system dependencies
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

# Create virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python3.12 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Optional pip proxy
RUN if [ -n "${http_proxy}" ]; then pip config set global.proxy "${http_proxy}"; fi

# Copy project files
COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
COPY demo/ /app/demo/
COPY deploy/docker/config/ /app/deploy/config/
COPY tools/ /app/tools/
COPY mibs/ /app/mibs/
COPY docker/entrypoint.sh /app/entrypoint.sh

# Install package inside venv
RUN pip install --upgrade pip \
 && pip install . \
 && pip install pysnmp-mibs

# Ensure config exists (copy from template if missing)
RUN mkdir -p /app/deploy/config \
 && if [ -f /app/deploy/config/system.json.template ] && \
       [ ! -f /app/deploy/config/system.json ]; then \
        cp /app/deploy/config/system.json.template \
           /app/deploy/config/system.json; \
    fi

# Set config path explicitly
ENV PYPNM_CONFIG=/app/deploy/config/system.json

# Create non-root user
RUN useradd -m -u 10001 -s /usr/sbin/nologin pypnm \
 && chown -R pypnm:pypnm /app

USER pypnm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:8000/docs || exit 1
  
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3.12", "-m", "uvicorn", "pypnm.api.main:app", "--host", "0.0.0.0", "--port", "8000"]