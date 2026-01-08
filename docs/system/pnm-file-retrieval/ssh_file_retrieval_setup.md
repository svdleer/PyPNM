# PyPNM - SCP And SFTP File Retrieval Setup

Guided Setup For Pulling PNM Files From A Remote TFTP Server Using SSH (SCP Or SFTP).

## Table Of Contents

- [Overview](#overview)
- [When To Use SCP Versus SFTP](#when-to-use-scp-versus-sftp)
- [Configuration Summary](#configuration-summary)
- [Running The SSH Setup Helper](#running-the-ssh-setup-helper)
- [Example Prompts And Answers](#example-prompts-and-answers)
- [Switching Retrieval Methods](#switching-retrieval-methods)
- [Verifying Operation In The Logs](#verifying-operation-in-the-logs)
- [Notes And Operational Tips](#notes-and-operational-tips)

## Overview

PyPNM can retrieve PNM capture files from a remote TFTP server over SSH. This is useful when:

- The cable modem uploads its PNM file to a TFTP server that is **not** the PyPNM host.
- The TFTP server is only reachable over a management network.
- Direct file system access to `/srv/tftp` or similar is not available to PyPNM.

To support this, PyPNM uses the `SSHConnector` helper and the `PnmFileRetrieval` section of `settings/system.json` to
pull files using either:

- **SCP** (copy via `scp` / `sshpass`), or
- **SFTP** (copy via the SSH SFTP subsystem).

This document describes how to configure SSH, generate and install an SSH key, and update `system.json` so that
PyPNM can automatically fetch PNM files over SCP or SFTP.

## When To Use SCP Versus SFTP

PyPNM supports both modes and treats them almost identically at a functional level. The main differences are:

- **SCP**
  - Uses the external `scp` command (optionally via `sshpass` for password-based auth).
  - Good fit when you already use `scp` operationally and want behavior identical to the shell.
  - In PyPNM, SCP is the default retrieval mode when `retrieval_method.method` is set to `"scp"`.

- **SFTP**
  - Uses the Paramiko SFTP client over an existing SSH connection.
  - Fully in-process, no external `scp` binary required once connected.
  - In PyPNM, SFTP is the primary mode when `retrieval_method.method` is set to `"sftp"`.

From the user’s perspective, you can treat them as interchangeable for file retrieval. The recommended pattern is:

- Use **SCP** as the default.
- Enable **SFTP** as a secondary option so you can flip between modes simply by changing `retrieval_method.method` in
  `settings/system.json`.

## Configuration Summary

All SSH-based retrieval settings live under `PnmFileRetrieval.retrieval_method` in `settings/system.json`.

A typical configuration looks like:

```json
{
  "PnmFileRetrieval": {
    "pnm_dir": ".data/pnm",
    "retrieval_method": {
      "method": "scp",
      "methods": {
        "scp": {
          "host": "tftp.example.net",
          "port": 22,
          "user": "pypnm",
          "password_enc": "",
          "private_key_path": "/home/pypnm/.ssh/id_rsa_pypnm",
          "remote_dir": "/srv/tftp"
        },
        "sftp": {
          "host": "tftp.example.net",
          "port": 22,
          "user": "pypnm",
          "password_enc": "",
          "private_key_path": "/home/pypnm/.ssh/id_rsa_pypnm",
          "remote_dir": "/srv/tftp"
        }
      }
    }
  }
}
```

Key points:

- `method` selects which retrieval path PyPNM uses at runtime:
  - `"scp"` → `_handle_scp_fetch()` in the service.
  - `"sftp"` → `_handle_sftp_fetch()` in the service.
- `remote_dir` is the directory on the remote TFTP/SSH host where the modem uploads PNM files.
- `pnm_dir` is PyPNM’s local directory where PNM files are stored after retrieval.
- `private_key_path` should point to a key that has its `.pub` installed into the remote user’s `~/.ssh/authorized_keys`.

Once these values are set, the only runtime decision is which method string is active.

## Running The SSH Setup Helper

PyPNM includes a Python helper script (for example `tools/pnm/setup_scp_key.py`) that automates the SSH key setup and
`settings/system.json` updates.

At a high level the helper:

1. Reads the current SCP/SFTP configuration from `SystemConfigSettings`.
2. Optionally clears the configured `private_key_path` (reset to password-only auth).
3. Generates a new SSH key pair if the configured `private_key_path` does not exist.
4. Installs the public key onto the remote user’s `~/.ssh/authorized_keys` via SSH.
5. Updates `settings/system.json` so that:
   - `PnmFileRetrieval.retrieval_method.methods.scp.private_key_path` is set.
   - `PnmFileRetrieval.retrieval_method.methods.sftp.private_key_path` is optionally set to the same path.
6. Optionally adds the public key to the **local** `~/.ssh/authorized_keys` (useful for localhost testing).

### Basic Invocation

From the PyPNM project root:

```bash
cd ~/Projects/PyPNM
./tools/pnm/setup_scp_key.py
```

The script will prompt you for:

- Whether to clear any existing key configuration.
- The key path to use (default is typically `~/.ssh/id_rsa_pypnm`).
- Whether to generate a new key if it does not exist.
- The SSH password for the configured user (one-time, to install the `.pub` key).
- Whether to apply the key to SCP and also to SFTP in `settings/system.json`.
- Whether to add the public key to the local `authorized_keys` file.

At the end, the helper prints the **public key** so that you can verify what was installed or paste it manually into
another system if needed.

Example output snippet:

```text
Using SSH user: pypnm@tftp.example.net
Using key path: /home/pypnm/.ssh/id_rsa_pypnm
Public key written to: /home/pypnm/.ssh/id_rsa_pypnm.pub

Public Key (/home/pypnm/.ssh/id_rsa_pypnm.pub):
ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDx... pypnm@tftp-host
```

## Example Prompts And Answers

This is a typical localhost workflow where PyPNM and the TFTP/SSH server run on the same machine:

1. Configure `settings/system.json` minimally:

   ```json
   "PnmFileRetrieval": {
     "pnm_dir": ".data/pnm",
     "retrieval_method": {
       "method": "scp",
       "methods": {
         "scp": {
           "host": "localhost",
           "port": 22,
           "user": "dev01",
           "password_enc": "",
           "private_key_path": "",
           "remote_dir": "/srv/tftp"
         },
         "sftp": {
           "host": "localhost",
           "port": 22,
           "user": "dev01",
           "password_enc": "",
           "private_key_path": "",
           "remote_dir": "/srv/tftp"
         }
       }
     }
   }
   ```

2. Run the helper:

   ```bash
   ./tools/pnm/setup_scp_key.py
   ```

3. Answer prompts roughly as follows:

   - Clear existing key configuration? → `n`
   - Use default key path `/home/dev01/.ssh/id_rsa_pypnm`? → `y`
   - Key does not exist, generate it now? → `y`
   - Enter SSH password for `dev01@localhost` when prompted.
   - Update `system.json` SCP `private_key_path` to this key? → `y`
   - Also use this key for SFTP? → `y`
   - Add public key to local `~/.ssh/authorized_keys`? → `y` (for localhost; optional otherwise)

4. Confirm that `settings/system.json` now contains:

   ```json
   "private_key_path": "/home/dev01/.ssh/id_rsa_pypnm"
   ```

   under both the `scp` and `sftp` method entries.

## Switching Retrieval Methods

Once SSH and `system.json` are set up, switching methods is simply:

- To use **SCP**:

  ```json
  "PnmFileRetrieval": {
    "retrieval_method": {
      "method": "scp",
      ...
    }
  }
  ```

- To use **SFTP**:

  ```json
  "PnmFileRetrieval": {
    "retrieval_method": {
      "method": "sftp",
      ...
    }
  }
  ```

PyPNM will dynamically choose `_handle_scp_fetch()` or `_handle_sftp_fetch()` based on this `method` string. The rest
of the JSON block (host, port, user, private_key_path, remote_dir) is read independently for each method.

## Verifying Operation In The Logs

When file retrieval runs, you should see log lines similar to:

- For SCP:

  ```text
  Retrieval method: scp
  SCP: Connecting to: tftp.example.net
  Authentication (publickey) successful!
  Successfully fetched file: ds_ofdm_rxmer_per_subcar_aa:bb:cc:dd:ee:ff_194_XXXXXXXXXX.bin
  ```

- For SFTP:

  ```text
  Retrieval method: sftp
  SFTP: Connecting to: tftp.example.net
  Authentication (publickey) successful!
  Successfully fetched file: ds_ofdm_rxmer_per_subcar_aa:bb:cc:dd:ee:ff_194_XXXXXXXXXX.bin
  ```

If you see:

```text
Authentication (publickey) failed.
Authentication (password) successful!
```

then SSH is falling back to the configured password. This is valid, but it usually means the public key was not added
to the remote user’s `authorized_keys`, or a different user is being used for SCP versus SFTP.

## Notes And Operational Tips

- You can safely keep both SCP and SFTP configured in `settings/system.json`. Only the method selected by
  `retrieval_method.method` is used at runtime.
- For production environments, favor key-based auth:
  - `password` can be left empty once the key is working.
  - Rotate keys by generating a new keypair and re-running the setup helper.
- For localhost testing, adding the public key to the local `authorized_keys` file allows passwordless SSH from PyPNM
  to itself, which is convenient for rapid development.
- If you manually edit `settings/system.json`, you do not need to restart PyPNM; `SystemConfigSettings.reload()` will
  pick up changes when called by the application.
