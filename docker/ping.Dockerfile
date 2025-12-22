FROM ghcr.io/svdleer/pypnm:v0.9.56.0
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*
