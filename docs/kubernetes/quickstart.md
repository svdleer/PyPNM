# Kubernetes quickstart (kind)

Copy-paste flow using the current release tag:

```bash
<<<<<<< HEAD
TAG="v1.0.27.0"
=======
TAG="v1.0.26.0"
>>>>>>> SpectrumAnalysis-Json-Return-Fix
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag ${TAG} --replicas 1
```

To target a specific namespace (useful for one PyPNM per CMTS):

```bash
<<<<<<< HEAD
TAG="v1.0.27.0"
=======
TAG="v1.0.26.0"
>>>>>>> SpectrumAnalysis-Json-Return-Fix
NAMESPACE="pypnm-cmts-a"
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source ghcr --tag ${TAG} --replicas 1 --namespace ${NAMESPACE}
```

To use a local image:

```bash
tools/k8s/pypnm_k8s_toolkit.sh --create --image-source local --replicas 1
```

Script-only deploy (no repo clone) is covered in [PyPNM on Kubernetes (kind)](pypnm-deploy.md).
