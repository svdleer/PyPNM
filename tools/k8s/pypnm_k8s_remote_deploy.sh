#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="default"
IMAGE_TAG="latest"
REPLICAS="1"
REF="main"
ACTION="create"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BANNER_PATH="${SCRIPT_DIR}/../banner.txt"

if [[ -f "${BANNER_PATH}" ]]; then
  cat "${BANNER_PATH}"
  echo
fi

usage() {
  cat <<'EOF'
PyPNM Kubernetes remote deploy (no repo clone required).

Usage:
  tools/k8s/pypnm_k8s_remote_deploy.sh [options]

Options:
  --create               Create resources from GHCR manifests (default).
  --teardown             Delete resources created by this script.
  --namespace <name>     Kubernetes namespace (default: default).
  --tag <tag>            GHCR tag (default: latest).
  --replicas <n>         Replica count (default: 1).
  --ref <git-ref>        Git ref for manifests (default: main).
  --help                 Show this help message.
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
    --create)
      ACTION="create"
      shift
      ;;
    --teardown)
      ACTION="teardown"
      shift
      ;;
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --tag)
      IMAGE_TAG="$2"
      shift 2
      ;;
    --replicas)
      REPLICAS="$2"
      shift 2
      ;;
    --ref)
      REF="$2"
      shift 2
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

require_cmd kubectl

REMOTE_KUSTOMIZE="github.com/svdleer/PyPNM//deploy/kubernetes/overlays/ghcr?ref=${REF}"

if [[ "${ACTION}" == "teardown" ]]; then
  kubectl delete -n "${NAMESPACE}" -k "${REMOTE_KUSTOMIZE}" || true
  exit 0
fi

if ! kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  kubectl create namespace "${NAMESPACE}"
fi

kubectl kustomize "${REMOTE_KUSTOMIZE}" | \
  sed "s|newTag: latest|newTag: ${IMAGE_TAG}|" | \
  kubectl apply -n "${NAMESPACE}" -f -

kubectl rollout status deploy/pypnm-api --namespace "${NAMESPACE}" --timeout=120s
kubectl scale deploy/pypnm-api --namespace "${NAMESPACE}" --replicas="${REPLICAS}"
