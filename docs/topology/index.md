# PNM File Retrieval Topologies

This page illustrates common network topologies for PNM file retrieval and how they map to the `PnmFileRetrieval.retrieval_method.method` setting in `system.json`.

## Table Of Contents

[Overview](#overview)  
[Local File Retrieval With Local TFTP Server](#local-file-retrieval-with-local-tftp-server)  
[SCP/SFTP File Retrieval With Remote TFTP Server](#scpsftp-file-retrieval-with-remote-tftp-server)  
[TFTP File Retrieval With Remote TFTP Server](#tftp-file-retrieval-with-remote-tftp-server)  
[Choosing A Topology With The Setup Script](#choosing-a-topology-with-the-setup-script)

## Overview

Each topology shows how three components interact:

- **Cable Modem (CM)** - Generates PNM files (for example, RxMER, FEC summary, constellation).  
- **TFTP Server** - Receives the PNM files from the CM.  
- **PyPNM Host** - Retrieves the files from the server into the local `.data/pnm` tree and performs decoding and analysis.

The selected topology is controlled by the `PnmFileRetrieval.retrieval_method.method` value in `src/pypnm/settings/system.json` (for example: `local`, `tftp`, `scp`, `sftp`).  

Other methods (`ftp`, `http`, `https`) are currently stubbed in the configuration but not supported by the tools or helper scripts.

## [Local File Retrieval](../system/pnm-file-retrieval/local.md) with Local TFTP Server

In this topology, the **PyPNM host and the TFTP server are the same machine**. The CM sends PNM files to a TFTP directory on the PyPNM host, and PyPNM uses a simple local file copy to ingest the captures.

Typical Lab use-case:

<p align="center">
  <picture>
    <source srcset="images/local-network-dark.svg"
            media="(prefers-color-scheme: dark)" />
    <img src="images/local-network-light.svg"
         alt="Local file retrieval with local TFTP server for PyPNM PNM file transfers" />
  </picture>
</p>

```json
"PnmFileRetrieval": {
  "retrieval_method": {
    "method": "local",
    "methods": {
      "local": {
        "src_dir": "/srv/tftp"
      }
    }
  }
}
```

## [SCP/SFTP File Retrieval](../system/pnm-file-retrieval/sftp.md) with Remote TFTP Server

In this topology, the **TFTP server is remote** (for example, on a CMTS lab host or a shared server), and PyPNM runs on a separate machine. The CM sends PNM files to the remote TFTP server; PyPNM then uses `scp` or `sftp` to pull the files down.

Typical Production use-case:

- Shared lab / production-like environments where TFTP is de-centralized.  
- When SSH-based access is required for security or compliance.  

<p align="center">
  <picture>
    <source srcset="images/scp-sftp-network-dark.svg"
            media="(prefers-color-scheme: dark)" />
    <img src="images/scp-sftp-network-light.svg"
         alt="SCP/SFTP file retrieval from remote TFTP server for PyPNM PNM file transfers" />
  </picture>
</p>

```json
"PnmFileRetrieval": {
  "retrieval_method": {
    "method": "scp",
    "methods": {
      "scp": {
        "host": "tftp.example.com",
        "port": 22,
        "user": "pnm",
        "password_enc": "",
        "private_key_path": "",
        "remote_dir": "/srv/tftp"
      }
    }
  }
}
```

or:

```json
"PnmFileRetrieval": {
  "retrieval_method": {
    "method": "sftp",
    "methods": {
      "sftp": {
        "host": "tftp.example.com",
        "port": 22,
        "user": "pnm",
        "password_enc": "",
        "private_key_path": "",
        "remote_dir": "/srv/tftp"
      }
    }
  }
}
```

## [TFTP File Retrieval](../system/pnm-file-retrieval/tftp.md) with Remote TFTP Server

In this topology, the **PyPNM host retrieves files directly via TFTP** from a remote TFTP server. The CM uploads PNM files to the remote TFTP server, and PyPNM pulls them using the `tftp` retrieval method.

<p align="center">
  <picture>
    <source srcset="images/tftp-network-dark.svg"
            media="(prefers-color-scheme: dark)" />
    <img src="images/tftp-network-light.svg"
         alt="TFTP file retrieval from remote TFTP server for PyPNM PNM file transfers" />
  </picture>
</p>

Typical Production (Non-Secure) use-case :

- Simple environments where TFTP access from PyPNM is allowed.  
- Legacy deployments that already use TFTP tooling and ACLs. 

Note: `PnmFileRetrieval.retrieval_method.tftp.remote_dir` is typically left as an empty string. In most deployments, the TFTP root directory is already defined on the TFTP server itself, and `remote_dir` would only be used if you need to pull from a specific subdirectory beneath that root.

```json
"PnmFileRetrieval": {
  "retrieval_method": {
    "method": "tftp",
    "methods": {
      "tftp": {
        "host": "tftp.example.com",
        "port": 69,
        "timeout": 5,
        "remote_dir": ""
      }
    }
  }
}
```

## Choosing A Topology With The Setup Script

Rather than editing `system.json` by hand, you can use the interactive setup script to select one of these topologies and populate the corresponding fields.

[PyPNM File Retrieval Methods](../system/pnm-file-retrieval/index.md)

Directly run from the project root:

```bash
./tools/pnm/pnm_file_retrieval_setup.py
```

Script location on [GitHub](https://github.com/PyPNMApps/pypnm/blob/main/tools/pnm/pnm_file_retrieval_setup.py):

The helper will:

- Back up `src/pypnm/settings/system.json` before any changes.  
- Ask which retrieval method you want (`local`, `tftp`, `scp`, `sftp`).  
- Prompt for host, port, user, password, private key path, and remote directory where applicable.  
- Update the `PnmFileRetrieval.retrieval_method` block to match the chosen topology.

You can re-run the script at any time if your lab topology changes (for example, moving from a local TFTP server to a remote SCP/SFTP-based workflow).
