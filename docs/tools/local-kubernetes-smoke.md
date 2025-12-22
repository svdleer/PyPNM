# Local Kubernetes smoke test

This helper builds the local image, loads it into kind, applies the manifests, and checks `/health`.

If Docker or kubectl permissions require it, the helper will re-run itself with `sudo`.

## Usage

```bash
./tools/local/local_kubernetes_smoke.sh
```

Custom cluster/image:

```bash
./tools/local/local_kubernetes_smoke.sh --cluster pypnm-dev --image pypnm:local --python 3.12
```

## What it does

- Builds `pypnm:local` (Python 3.12).
- Loads the image into kind (`pypnm-dev`).
- Applies `deploy/kubernetes`.
- Waits for rollout, then checks `http://127.0.0.1:8000/health`.
