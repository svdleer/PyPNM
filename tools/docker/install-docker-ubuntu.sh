#!/usr/bin/env bash
set -euo pipefail

ACTION="install"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANNER_PATH="${SCRIPT_DIR}/../banner.txt"

if [[ -f "${BANNER_PATH}" ]]; then
  cat "${BANNER_PATH}"
  echo
fi

usage() {
  cat <<'EOF'
Install Docker Engine + Compose on Ubuntu 22.04/24.04.

Usage:
  tools/docker/install-docker-ubuntu.sh [--uninstall]

Options:
  --uninstall    Remove Docker packages and repo files installed by this script.
  --help         Show this help message.
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      ACTION="uninstall"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd sudo

if [[ "${ACTION}" == "uninstall" ]]; then
  sudo apt-get remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || true
  sudo apt-get autoremove -y || true
  sudo rm -f /etc/apt/sources.list.d/docker.sources
  sudo rm -f /etc/apt/keyrings/docker.asc
  sudo apt-get update
  exit 0
fi

require_cmd curl

sudo rm -f /etc/apt/sources.list.d/docker.sources
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<SOURCES
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
SOURCES

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

docker --version
Docker_Compose_Version=$(docker compose version || true)
if [[ -n "${Docker_Compose_Version}" ]]; then
  echo "${Docker_Compose_Version}"
fi

sudo docker run --rm hello-world

cat <<'INFO'

Optional (non-production): allow your user to run docker without sudo.

  sudo groupadd docker || true
  sudo usermod -aG docker "$USER"

Log out and back in for group changes to apply.
INFO
