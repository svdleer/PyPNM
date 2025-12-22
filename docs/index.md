# PyPNM documentation hub

Use this page to grab the right guide no matter where you are in the journey—installing, configuring, operating, or contributing.

## New to PyPNM? (Start here)

- [Project overview](https://github.com/svdleer/PyPNM/blob/main/README.md) - why PyPNM exists plus installer basics.
- [Install flow](https://github.com/svdleer/PyPNM/blob/main/README.md#getting-started) - clone, run `./install.sh`, and bring up the FastAPI stack.
- [Docker install & usage](docker/install.md) - helper script, manual tarball flow, offline notes, prerequisites.
- [Docker commands](docker/commands.md) - common compose/logs/config/restart helpers for PyPNM.
- [Topology guide](topology/index.md) - pick a PNM file retrieval method before you touch `system.json`.
- [System configuration quick tour](system/menu.md) - understand the interactive helpers before editing the config.

## Configure and operate

- [System configuration reference](system/system-config.md) - every field in `src/pypnm/settings/system.json`.
- [PNM file retrieval helpers](system/pnm-file-retrieval/index.md) - local, TFTP, SCP/SFTP workflows and setup scripts.
- [CLI/service usage](system/pypnm-cli.md) - run the FastAPI launcher and related scripts.
- [Operational tools](tools/index.md) - log collection, capture orchestration, and automation helpers.
- [Scripts](scripts/index.md) - one-liners in `scripts/` for installs, secrets, CI helpers.
- [Demo mode guide](https://github.com/svdleer/PyPNM/blob/main/demo/README.md) - how the sample data environment is staged and how to reset it.

## Develop and automate

- [API reference](api/index.md) - REST endpoints plus Python helper library docs.
- [Examples](examples/index.md) - runnable walkthroughs hitting the API.
- [Tests](tests/index.md) - how to execute and extend the automated test suites.

## Release and support

- [Release strategy](release/release-strategy.md) - versioning, tagging, and publishing flow.
- [Issues and support bundles](issues/index.md) - how to report bugs, gather diagnostics, and share logs.
- [Security](https://github.com/svdleer/PyPNM/blob/main/SECURITY.md) - responsible disclosure guidelines.

## Need more context?

- [Style guide](style-guide.md) - guidelines for writing or updating documentation.
- [Project roadmap / README next steps](https://github.com/svdleer/PyPNM/blob/main/README.md#next-steps) - suggestions on what to explore after installation.
