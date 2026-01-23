# syntax=docker/dockerfile:1.6

ARG PYTHON_VERSION=3.12
FROM ubuntu:24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ca-certificates \
    gosu \
    iputils-ping \
    wget \
    python3.12 \
    python3-pip \
    python3.12-venv \
    snmp \
    snmp-mibs-downloader \
 && download-mibs \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
COPY demo/ /app/demo/
COPY deploy/docker/config/ /app/deploy/config/
COPY tools/ /app/tools/
COPY mibs/ /app/mibs/
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN python3.12 -m pip install --upgrade pip --break-system-packages \
 && python3.12 -m pip install . --break-system-packages \
 && useradd -m -u 10001 -s /usr/sbin/nologin pypnm \
 && chmod +x /app/entrypoint.sh \
 && if [ -f /app/deploy/config/system.json.template ] && [ ! -f /app/deploy/config/system.json ]; then cp /app/deploy/config/system.json.template /app/deploy/config/system.json; fi \
 && mkdir -p /usr/share/snmp/mibs \
 && cp /app/mibs/*.my /usr/share/snmp/mibs/ 2>/dev/null || true \
 && cp /app/mibs/*.mib /usr/share/snmp/mibs/ 2>/dev/null || true \
 && cp /app/mibs/*.txt /usr/share/snmp/mibs/ 2>/dev/null || true

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3.12", "-m", "uvicorn", "pypnm.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
