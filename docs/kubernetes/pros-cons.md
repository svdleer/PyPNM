# Kubernetes approach: pros and cons

## Pros

- Repeatable local testing with kind and a single command.
- Easy to switch between GHCR and local images.
- Simple scaling via a `--replicas` flag.
- Health checks are consistent (`/health`).

## Cons

- Kind is single-node and may not reflect multi-node behavior.
- Local image loading bypasses registry pull/auth issues.
- EmptyDir volumes hide persistence concerns.
