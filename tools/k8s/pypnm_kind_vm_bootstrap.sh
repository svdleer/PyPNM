#!/usr/bin/env bash
set -euo pipefail

KIND_VERSION="${KIND_VERSION:-v0.24.0}"
KUBECTL_VERSION="${KUBECTL_VERSION:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANNER_PATH="${SCRIPT_DIR}/../banner.txt"

if [[ -f "${BANNER_PATH}" ]]; then
  cat "${BANNER_PATH}"
  echo
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd sudo

if [[ -z "${KUBECTL_VERSION}" ]]; then
  KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

if ! command -v kubectl >/dev/null 2>&1; then
  curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o "${TMP_DIR}/kubectl"
  sudo install -m 0755 "${TMP_DIR}/kubectl" /usr/local/bin/kubectl
  kubectl version --client
else
  kubectl version --client
fi

if ! command -v kind >/dev/null 2>&1; then
  curl -fsSL "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64" -o "${TMP_DIR}/kind"
  sudo install -m 0755 "${TMP_DIR}/kind" /usr/local/bin/kind
  kind version
else
  kind version
fi

cat <<'INFO'

Next steps:
- Install Docker if it is not already present.
- Create a kind cluster and deploy PyPNM from GHCR using the toolkit.
INFO
