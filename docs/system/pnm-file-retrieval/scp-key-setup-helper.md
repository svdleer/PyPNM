# PyPNM System - SCP/SFTP Key Setup Helper

Helper Utility To Configure SSH Key-Based SCP/SFTP File Retrieval For PyPNM.

## Table Of Contents

[Overview](#overview)

[Script Location And Invocation](#script-location-and-invocation)

[Related System Configuration](#related-system-configuration)

[First-Time Key Setup Workflow](#first-time-key-setup-workflow)

[Clearing Or Resetting Keys](#clearing-or-resetting-keys)

[Using The Generated Key On Other Systems](#using-the-generated-key-on-other-systems)

[Troubleshooting Notes](#troubleshooting-notes)

## Overview

PyPNM can retrieve PNM capture files from a remote server using SCP or SFTP instead of copying directly from a local
TFTP directory. The **SCP Key Setup Helper** automates the local SSH key creation and remote key installation required
for passwordless (or reduced password) file transfers.

The helper script:

- Reads the current SCP/SFTP configuration from `SystemConfigSettings`.
- Optionally clears an existing key pair (local files and JSON path).
- Generates a dedicated RSA key pair for PyPNM if needed.
- Installs the public key into the remote user's `~/.ssh/authorized_keys`.
- Optionally updates `settings/system.json` with the new `private_key_path` for both SCP and SFTP.
- Optionally adds the same public key into the **local** `~/.ssh/authorized_keys` for loopback/self-testing.

## Script Location And Invocation

The helper lives under the PyPNM **system** utilities directory, for example:

```text
src/pypnm/system/scp_key_setup.py
```

From the PyPNM project root you can invoke it with:

```bash
(.env) PyPNM$ python src/pypnm/system/scp_key_setup.py
```

Adjust the path if your layout differs (for example if you place the script under a `tools/` directory). The script is
interactive and should be run from a terminal.

## Related System Configuration

The helper script is tightly coupled to the following sections of `settings/system.json`:

```json
"PnmFileRetrieval": {
  "retrieval_method": {
    "method": "scp",
    "methods": {
      "scp": {
        "host": "localhost",
        "port": 22,
        "user": "dev01",
        "password_enc": "",
        "private_key_path": "/home/dev01/.ssh/id_rsa_pypnm",
        "remote_dir": "/srv/tftp"
      },
      "sftp": {
        "host": "localhost",
        "port": 22,
        "user": "dev01",
        "password_enc": "",
        "private_key_path": "/home/dev01/.ssh/id_rsa_pypnm",
        "remote_dir": "/srv/tftp"
      }
    }
  }
}
```

Key points:

- **SCP / SFTP Host**: The `host`, `port`, and `user` fields define where the capture files live.
- **Password**: Used only for the initial public-key installation step (and for password-based fallback if you clear
  keys).
- **private_key_path**: The path to the private key that PyPNM should use when performing SCP/SFTP fetches.
- **remote_dir**: Directory on the remote server where PNM capture files are stored (for example `/srv/tftp`).

The helper uses `SystemConfigSettings.get_config_path()` to find the active `settings/system.json` and will update only
the `private_key_path` fields for the `scp` and `sftp` sections when you approve those prompts.

## First-Time Key Setup Workflow

Typical first-time setup for key-based SCP/SFTP looks like this:

1. **Ensure SCP/SFTP config is present**

   Edit `settings/system.json` so the `PnmFileRetrieval.retrieval_method.methods.scp` and `.sftp` blocks contain at least:

   - `host`, `port`, `user`
   - Optional `password` (for first-time installation)
   - `remote_dir` pointing to your TFTP/SCP directory
   - `private_key_path` can be empty on first run (`""`)

2. **Run the helper**

   ```bash
   (.env) PyPNM$ python src/pypnm/system/scp_key_setup.py
   ```

3. **Select or confirm private key path**

   - If `private_key_path` is empty, the helper proposes a default such as `~/.ssh/id_rsa_pypnm`.
   - You can accept the default or enter a custom path.

4. **Generate key pair (if needed)**

   If the selected private key does not exist, the helper asks:

   > Private key '~/.ssh/id_rsa_pypnm' does not exist. Generate it now?

   Answer **`y`** to have it generate a new RSA key pair and corresponding `.pub` file.

5. **Provide remote password (one-time)**

   If no password is configured, you will be prompted for the SSH password:

   > Enter SSH password for dev01@localhost:

   The helper uses this password to connect once and append the public key to the remote
   `~/.ssh/authorized_keys` file.

6. **Update system.json with private_key_path**

   After a successful install, the helper offers to write the resolved key path into `settings/system.json`:

   - Update SCP `private_key_path`
   - Optionally also set SFTP `private_key_path` to the same value

7. **Optionally add key to local authorized_keys**

   For loopback or self-testing, the helper can append the same public key to your local
   `~/.ssh/authorized_keys` file as well.

8. **Public key summary output**

   At the end the script prints a short summary and the full public key between markers:

   ```text
   ----- BEGIN PyPNM Public Key -----
   ssh-rsa AAAA... user@host
   ----- END PyPNM Public Key -----
   ```

   You can copy this block into other systems if you want additional servers to accept the same key.

## Clearing Or Resetting Keys

If a `private_key_path` is already configured in `settings/system.json`, the helper detects it and offers to clear it:

1. Run the helper again.

2. When prompted:

   > Do you want to clear this key and use password-only SCP/SFTP?

   Answer **`y`** to remove the local private/public key files.

3. Optionally allow the helper to:

   - Set `PnmFileRetrieval.retrieval_method.methods.scp.private_key_path` to an empty string.
   - Set `PnmFileRetrieval.retrieval_method.methods.sftp.private_key_path` to an empty string.

After this, SCP/SFTP falls back to password-based authentication using the configured `user` and `password` fields until
you run the helper again to re-establish key-based access.

## Using The Generated Key On Other Systems

The helper does not attempt to modify any other hosts beyond the configured SCP/SFTP server. To reuse the same key:

1. Run the helper and let it complete successfully.
2. Copy the printed public key block from the console.
3. On the additional server(s), append that key line to the target user's `~/.ssh/authorized_keys` and ensure the
   file permissions are correct (typically `600` for `authorized_keys` and `700` for `~/.ssh`).

As long as PyPNM can reach those servers and the `host`, `user`, and `private_key_path` are configured appropriately,
SCP/SFTP will work without additional password prompts.

## Troubleshooting Notes

- **Paramiko logs public-key failure first**

  When key-based authentication is not yet configured, you may see log lines similar to:

  ```text
  Authentication (publickey) failed.
  Authentication (password) successful!
  ```

  This is normal during the first run; once the key is installed and configured, authentication should succeed with
  `Authentication (publickey) successful!` and no password prompt.

- **Config path resolution**

  The helper relies on `SystemConfigSettings.get_config_path()` to locate the active `settings/system.json`. If you
  maintain multiple configuration files, make sure your environment is pointing to the expected one before running the
  helper.

- **Permissions on ~/.ssh**

  If you encounter errors writing or reading `~/.ssh/authorized_keys`, double-check:

  - Directory exists and is owned by the correct user.
  - Permissions on `~/.ssh` are `700` and on `authorized_keys` are `600`.
  - SELinux or other security mechanisms are not blocking SSH from reading the files.

Once the helper has been run and `private_key_path` is set in `settings/system.json`, PyPNM SCP/SFTP retrieval should
work transparently for PNM capture file downloads.
