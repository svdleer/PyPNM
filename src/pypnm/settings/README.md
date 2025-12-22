# Config Symlink

`system.json` in this directory is a symlink to `deploy/docker/config/system.json`.
The running container mounts `/app/config/system.json` from that deploy path,
so keeping them linked ensures:

- The baked-in default and the deploy config stay in sync.
- Edits made via config-menu or direct file edits hit the same file the
  container reads.

If you need to regenerate or relocate the config, update `deploy/docker/config/system.json`
and recreate the symlink here. Do not commit secrets to version control.
