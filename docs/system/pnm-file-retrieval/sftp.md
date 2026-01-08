# SFTP PNM File Retrieval Setup (Config Menu)

This guide shows how to configure **SFTP** PNM file retrieval using the PyPNM `pnm_file_retrieval_setup.py` helper. The
selected method becomes the active `PnmFileRetrieval.retrieval_method.method` in `src/pypnm/settings/system.json`.

When you provide credentials, the script tests SSH connectivity and reports success or failure. If you configure a private
key, the script prints the corresponding RSA public key so you can install it on the remote host.

## Table Of Contents

- [Run The Setup Script](#run-the-setup-script)
- [What Gets Written To system.json](#what-gets-written-to-systemjson)
- [Authentication And Connection Testing](#authentication-and-connection-testing)
  - [Password Authentication](#password-authentication)
  - [Private Key Authentication](#private-key-authentication)
  - [When Both Are Configured](#when-both-are-configured)
- [SOP: Install The PyPNM Public Key On The Remote Host](#sop-install-the-pypnm-public-key-on-the-remote-host)

## Run The Setup Script

```bash
source PyPNM/.env/bin/activate
(.env) PyPNM$ ./tools/pnm/pnm_file_retrieval_setup.py
INFO PnmFileRetrievalConfigurator: Using configuration file: PyPNM/src/pypnm/settings/system.json
INFO PnmFileRetrievalConfigurator: Created backup: PyPNM/src/pypnm/settings/system.bak.<timestamp>.json

Select PNM File Retrieval Method:
  1) local  - Copy from local src_dir
  2) tftp   - Download from TFTP server
  3) sftp   - Download from SFTP server
  q) Quit   - Exit without changes

Enter choice [1-3 or q to quit]: 3
INFO PnmFileRetrievalConfigurator: Selected retrieval method: sftp

Configure SFTP PNM File Retrieval:
Enter SSH host [localhost]:
Enter SSH port for localhost [22]:
Enter SSH username [dev01]:
Enter remote_dir [/srv/tftp]:

Authentication Options:
  You may configure password, private key, or both.
  At least one of them must be provided.
  Passwords are stored encrypted as ENC[v1]:... in password_enc.

Configure password authentication? [y/N]: y
Configure private key authentication? [y/N]: y
Enter SSH password (leave blank to clear, or paste ENC[...] token):
Enter private key path [~/.ssh/id_rsa_pypnm]:
INFO PnmFileRetrievalConfigurator: Testing SFTP connection to dev01@localhost:22 ...
INFO PnmFileRetrievalConfigurator: SSH connection test succeeded.
INFO PnmFileRetrievalConfigurator: PNM file retrieval configuration complete.

======================================================================
 SFTP Public Key (Add To Your PNM File Server)
======================================================================
ssh-rsa <RSA-PUBLIC-KEY> dev01@pypnm-host

Add this key to the remote user's ~/.ssh/authorized_keys on the host(s)
you configured for sftp file retrieval.
======================================================================
```

## What Gets Written To system.json

SFTP settings are stored under:

- `PnmFileRetrieval.retrieval_method.method = "sftp"`
- `PnmFileRetrieval.retrieval_method.methods.sftp.*`

Typical keys written for SFTP:

- `host`
- `port`
- `user`
- `remote_dir`
- `private_key_path`
- `password_enc`

`password_enc` is the only supported password field. It stores either:

- An encrypted token like `ENC[v1]:...`, or
- An empty string when password authentication is not configured.

## Authentication And Connection Testing

### Password Authentication

When you enable password authentication:

- Your password is encrypted and stored as `password_enc` (or you may paste an existing `ENC[...]` token).
- The script immediately attempts an SSH connection with:
  - host
  - port
  - username
  - password (decrypted at connect time)

On success, the script logs:

- `SSH connection test succeeded.`

On failure, the script exits with a descriptive error.

### Private Key Authentication

When you enable private key authentication:

- The script stores `private_key_path` (default: `~/.ssh/id_rsa_pypnm`).
- If a matching public key file exists (`<private_key_path>.pub`), the script prints the public key so you can install it
  on the remote server.

### When Both Are Configured

If both `private_key_path` and `password_enc` are configured, Paramiko will attempt key-based authentication and may fall
back to password authentication if the key is rejected and a password is available. Which method ultimately succeeds is
determined by the server configuration and the credentials you provided. In practice, most OpenSSH servers will accept a
valid public key before evaluating password authentication, and the SSH logs will show which authentication succeeded.

## SOP: Install The PyPNM Public Key On The Remote Host

These steps assume an Ubuntu/OpenSSH remote host. Adapt as required for your environment.

1. **Log Into The Remote PNM File Server**  
   Use a privileged account (SSH or console) to access the host where PNM files are stored (for example, `/srv/tftp`).

2. **Identify The Target User Account**  
   Choose the user that PyPNM will authenticate as. This must match the `user` you configured in the setup script.

3. **Create The .ssh Directory (If Needed)**  
   If the home directory is non-standard, adjust paths accordingly.

   ```bash
   REMOTE_USER="<remote-user>"
   sudo -u "${REMOTE_USER}" mkdir -p "/home/${REMOTE_USER}/.ssh"
   sudo -u "${REMOTE_USER}" chmod 700 "/home/${REMOTE_USER}/.ssh"
   ```

4. **Append The Public Key To authorized_keys**  
   Copy the `ssh-rsa ...` line printed by the setup script and append it to the remote user's `authorized_keys`.

   ```bash
   REMOTE_USER="<remote-user>"
   RSA_PUBLIC_KEY='ssh-rsa <RSA-PUBLIC-KEY> dev01@pypnm-host'  # Replace with the exact line printed by the setup script

   sudo -u "${REMOTE_USER}" bash -c "echo '${RSA_PUBLIC_KEY}' >> /home/${REMOTE_USER}/.ssh/authorized_keys"
   sudo -u "${REMOTE_USER}" chmod 600 "/home/${REMOTE_USER}/.ssh/authorized_keys"
   ```

   Notes:
   - Use single quotes for `RSA_PUBLIC_KEY` so the key contents are not shell-expanded.
   - Keep the key line intact. Do not wrap or reformat it.

5. **Verify Ownership And Permissions**

   ```bash
   REMOTE_USER="<remote-user>"
   ls -ld "/home/${REMOTE_USER}/.ssh"
   ls -l  "/home/${REMOTE_USER}/.ssh/authorized_keys"
   ```

   Expected permissions:
   - `.ssh` directory: `700`
   - `authorized_keys`: `600`

6. **Confirm Key-Based SSH Access**  
   From the PyPNM host:

   ```bash
   ssh -i ~/.ssh/id_rsa_pypnm <remote-user>@<remote-host>
   ```

   If login succeeds without prompting for a password (aside from first-use host key confirmation), key-based
   authentication is configured correctly.

7. **Re-run Or Test PyPNM Retrieval**  
   After the key is installed and verified, run your normal PyPNM capture workflow. PyPNM should be able to retrieve PNM
   files from the configured `remote_dir` without interactive prompts.
