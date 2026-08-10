# Configuration Sources

`system.json` in this directory is a source-development symlink to
`deploy/docker/config/system.json`.

Containers do not rewrite this directory. They select
`/app/config/system.json` through `PYPNM_CONFIG_PATH`; that runtime file belongs
on a persistent volume or deployment-owned bind mount. On first start, the
entrypoint seeds an empty runtime config from the packaged deploy config or
its template.

Do not commit secrets to version control.
