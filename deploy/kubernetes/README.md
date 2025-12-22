# Kubernetes quickstart (kind)

This folder contains minimal Kubernetes manifests for PyPNM.

## Apply

```bash
kubectl apply -k deploy/kubernetes
kubectl get pods
```

## Health check

```bash
kubectl port-forward deploy/pypnm-api 8000:8000
curl -i http://127.0.0.1:8000/health
```

## Config overrides (non-interactive)

Use a patch file and initContainer to modify `/app/config/system.json` on startup.

```bash
kubectl create configmap pypnm-config-patch \
  --from-file=patch.json=/path/to/patch.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then add an initContainer to apply the patch (see `docs/kubernetes/pypnm-deploy.md`).
