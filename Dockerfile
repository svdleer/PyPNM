FROM ubuntu:24.04

ARG PYTHON_VERSION=3.12
ARG http_proxy
ARG https_proxy
ARG no_proxy

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
  PIP_CONFIG_FILE=/etc/pip.conf \
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
      python${PYTHON_VERSION} \
      python3-pip \
      python${PYTHON_VERSION}-venv \
 && rm -rf /var/lib/apt/lists/*

# Create virtual environment
ENV VIRTUAL_ENV=/opt/venv
RUN python${PYTHON_VERSION} -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Optional pip proxy (system-wide so it works for root and non-root users)
RUN if [ -n "${http_proxy}" ]; then \
      printf "[global]\nproxy = %s\n" "${http_proxy}" > /etc/pip.conf; \
    fi

# Copy project files
COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/
COPY demo/ /app/demo/
COPY deploy/docker/config/ /app/deploy/config/
COPY tools/ /app/tools/
COPY mibs/ /app/mibs/
COPY docker/entrypoint.sh /app/entrypoint.sh

# Install package inside venv. Pin Pydantic explicitly so local and
# container schema/runtime behavior remain identical.
RUN pip install --upgrade pip \
 && pip install "pydantic==2.12.5" . \
 && pip install pysnmp-mibs

RUN mkdir -p /app/deploy/config \
 && if [ -f /app/deploy/config/system.json.template ]; then \
      cp -n /app/deploy/config/system.json.template \
            /app/deploy/config/system.json; \
    fi \
 && ls -l /app/deploy/config

# Select the writable runtime configuration. The entrypoint seeds this path
# from the packaged defaults on first start when the config volume is empty.
ENV PYPNM_CONFIG=/app/config/system.json

# Create non-root user
RUN useradd -m -u 10001 -s /usr/sbin/nologin pypnm \
 && chown -R pypnm:pypnm /app \
 && chown -R pypnm:pypnm /opt/venv

USER root

EXPOSE 8000

# Clear proxy env vars set during build — prevents wget/curl inside the running
# container from routing healthcheck requests through the build-time proxy
ENV http_proxy="" \
    https_proxy="" \
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    no_proxy="localhost,127.0.0.1,.oss.local" \
    NO_PROXY="localhost,127.0.0.1,.oss.local"

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q -O /dev/null http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "pypnm.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--ws-max-size", "67108864"]