#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import getpass
import json
import logging
import os
import sys

from pypnm.config.system_config_settings import SystemConfigSettings
from pypnm.lib.ssh.ssh_connector import SSHConnector, SecureTransferMode


class ScpKeySetup:
    """
    Helper Utility To Configure Or Clear SSH Key-Based SCP/SFTP For PyPNM.

    This tool reads the current SCP configuration from SystemConfigSettings,
    optionally clears the configured private key (and local key files), or
    ensures that a private key exists locally (generating one if requested)
    and installs the corresponding public key into the remote user's
    ~/.ssh/authorized_keys file using password authentication.

    It can optionally update the system configuration JSON file (as reported
    by SystemConfigSettings.get_config_path()) to record the effective
    private_key_path for the SCP and SFTP methods, and can also add the same
    public key to the local ~/.ssh/authorized_keys file if requested.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

    def run(self) -> None:
        """
        Execute The SCP Key Setup Or Clear Workflow.

        Steps:
        - Reload SystemConfigSettings.
        - Resolve SCP host, port, user, password, and private key path.
        - If a private key path is configured, offer to clear it and delete
          the local key files, leaving SCP/SFTP to use password-only.
        - If not clearing, resolve the effective private key path.
        - If the private key does not exist, prompt to generate it.
        - Validate that the public key exists.
        - Use password-based SSH to install the public key on the remote host.
        - Optionally update the system configuration JSON with the effective
          key path for SCP and SFTP.
        - Optionally add the public key to the local authorized_keys file.
        """
        SystemConfigSettings.reload()

        config_path      = SystemConfigSettings.get_config_path()
        retrieval_method = SystemConfigSettings.retrieval_method()
        if retrieval_method != "scp":
            self.logger.info(
                "Current retrieval method is '%s' (not 'scp'); continuing anyway.",
                retrieval_method,
            )

        host            = SystemConfigSettings.scp_host()
        port            = SystemConfigSettings.scp_port()
        user            = SystemConfigSettings.scp_user()
        configured_key  = SystemConfigSettings.scp_private_key_path()
        configured_pass = SystemConfigSettings.scp_password()

        if not host or not user:
            self.logger.error("SCP host or user is not configured; aborting.")
            return

        if configured_key:
            self.logger.info("Configured private key path: %s", configured_key)
            if self._prompt_yes_no(
                "Do you want to clear this key and use password-only SCP/SFTP?"
            ):
                self._clear_local_key(configured_key)
                if self._prompt_yes_no(
                    f"Also update {config_path} to set SCP private_key_path to empty?"
                ):
                    self._update_system_json_private_key_path(
                        config_path = config_path,
                        new_path    = "",
                    )
                if self._prompt_yes_no(
                    f"Also update {config_path} to set SFTP private_key_path to empty?"
                ):
                    self._update_system_json_sftp_private_key_path(
                        config_path = config_path,
                        new_path    = "",
                    )
                self.logger.info(
                    "Private key cleared. SCP/SFTP will fall back to password-based auth."
                )
                return

        effective_key_path = self._resolve_key_path(configured_key)
        if not effective_key_path:
            self.logger.error("Unable to determine a private key path; aborting.")
            return

        if not os.path.exists(os.path.expanduser(effective_key_path)):
            if not self._prompt_yes_no(
                f"Private key '{effective_key_path}' does not exist. Generate it now?"
            ):
                self.logger.error("Private key is required for key-based SCP/SFTP; aborting.")
                return
            if not self._generate_key(effective_key_path):
                self.logger.error("Failed to generate private key; aborting.")
                return

        public_key_path = f"{effective_key_path}.pub"
        if not os.path.exists(os.path.expanduser(public_key_path)):
            self.logger.error("Missing public key file '%s'; aborting.", public_key_path)
            return

        password = configured_pass
        if not password:
            self.logger.info("No SCP password configured; prompt for password to install public key.")
            password = getpass.getpass(prompt = f"Enter SSH password for {user}@{host}: ")
            if not password:
                self.logger.error("Password is required to install public key; aborting.")
                return

        if not self._install_public_key(
            host        = host,
            port        = port,
            user        = user,
            password    = password,
            public_key  = public_key_path,
            private_key = effective_key_path,
        ):
            self.logger.error("Failed to install public key on remote host.")
            return

        self.logger.info("")
        self.logger.info("SCP key-based authentication is now configured for %s@%s.", user, host)

        if self._prompt_yes_no(
            f"Update {config_path} with SCP private_key_path = '{effective_key_path}'?"
        ):
            if self._update_system_json_private_key_path(
                config_path = config_path,
                new_path    = effective_key_path,
            ):
                self.logger.info("Updated %s with new SCP private_key_path.", config_path)
            else:
                self.logger.error("Failed to update %s; please edit SCP section manually.", config_path)
        else:
            self.logger.info(
                "Ensure %s contains:\n"
                "  PnmFileRetrieval.retrieval_method.methods.scp.private_key_path = '%s'",
                config_path,
                effective_key_path,
            )

        if self._prompt_yes_no(
            f"Also use this key for SFTP in {config_path}?"
        ):
            if self._update_system_json_sftp_private_key_path(
                config_path = config_path,
                new_path    = effective_key_path,
            ):
                self.logger.info("Updated %s with new SFTP private_key_path.", config_path)
            else:
                self.logger.error("Failed to update %s; please edit SFTP section manually.", config_path)

        if self._prompt_yes_no(
            "Also add this public key to your local ~/.ssh/authorized_keys?"
        ):
            if self._add_public_key_to_local_authorized_keys(public_key_path):
                self.logger.info("Local authorized_keys updated with this public key.")
            else:
                self.logger.error("Failed to update local authorized_keys; see log for details.")

        self._print_public_key_summary(
            public_key_path  = public_key_path,
            private_key_path = effective_key_path,
        )

    def _resolve_key_path(self, configured: str) -> str:
        """
        Resolve The Effective Private Key Path.

        If a path is configured and not cleared, it is used as-is. Otherwise
        a default path of '~/.ssh/id_rsa_pypnm' is proposed and confirmed
        with the user.
        """
        if configured:
            self.logger.info("Using configured private key path: %s", configured)
            return configured

        default_path = os.path.expanduser("~/.ssh/id_rsa_pypnm")
        self.logger.info(
            "No private key path configured for SCP; defaulting to '%s'.",
            default_path,
        )
        if self._prompt_yes_no(f"Use default private key path '{default_path}'?"):
            return default_path

        custom = input("Enter custom private key path (or leave blank to abort): ").strip()
        if not custom:
            return ""
        return custom

    def _generate_key(self, key_path: str) -> bool:
        """
        Generate A New RSA Key Pair At The Specified Path.

        Delegates to SSHConnector.generate_ssh_key_pair(), expanding '~'
        before passing the final path to Paramiko.
        """
        expanded = os.path.expanduser(key_path)
        self.logger.info("Generating new RSA key pair at '%s'...", expanded)
        if SSHConnector.generate_ssh_key_pair(key_path = expanded, key_size = 2048):
            self.logger.info("Private key generated successfully.")
            return True
        self.logger.error("SSHConnector.generate_ssh_key_pair() reported failure.")
        return False

    def _install_public_key(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        public_key: str,
        private_key: str,
    ) -> bool:
        """
        Install The Public Key On The Remote Host's Authorized Keys.

        Connects to the remote host using password authentication and calls
        SSHConnector.install_public_key(public_key_path). The private_key
        path is stored on the connector for future SCP/SFTP operations.
        """
        connector = SSHConnector(
            hostname      = host,
            username      = user,
            port          = port,
            transfer_mode = SecureTransferMode.SCP,
        )

        self.logger.info("Connecting to %s@%s:%d to install public key...", user, host, port)
        if not connector.connect(password = password, private_key_path = None):
            self.logger.error("SSH password authentication failed; cannot install public key.")
            return False

        try:
            if not connector.install_public_key(os.path.expanduser(public_key)):
                self.logger.error("install_public_key() returned failure.")
                return False
            self.logger.info("Public key installed successfully on remote host.")
            return True
        finally:
            connector.disconnect()

    def _clear_local_key(self, key_path: str) -> None:
        """
        Remove The Local Private/Public Key Files For The Given Path.

        Attempts to delete both the private key and its matching .pub file,
        ignoring missing files but logging what was removed.
        """
        expanded_private = os.path.expanduser(key_path)
        expanded_public  = f"{expanded_private}.pub"

        if os.path.exists(expanded_private):
            try:
                os.remove(expanded_private)
                self.logger.info("Removed private key file: %s", expanded_private)
            except OSError as exc:
                self.logger.error("Failed to remove private key file '%s': %s", expanded_private, exc)
        else:
            self.logger.info("Private key file does not exist: %s", expanded_private)

        if os.path.exists(expanded_public):
            try:
                os.remove(expanded_public)
                self.logger.info("Removed public key file: %s", expanded_public)
            except OSError as exc:
                self.logger.error("Failed to remove public key file '%s': %s", expanded_public, exc)
        else:
            self.logger.info("Public key file does not exist: %s", expanded_public)

    def _update_system_json_private_key_path(self, config_path: str, new_path: str) -> bool:
        """
        Update The SCP private_key_path In The System Configuration JSON.

        This function reads the JSON configuration file at config_path,
        updates only the PnmFileRetrieval.retrieval_method.methods.scp
        .private_key_path field, and writes the file back to disk.
        """
        if not os.path.exists(config_path):
            self.logger.error("Configuration file not found: %s", config_path)
            return False

        try:
            with open(config_path, "r", encoding = "utf-8") as f:
                data: dict[str, object] = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.error("Failed to read %s: %s", config_path, exc)
            return False

        try:
            pnm_file_retrieval = data.get("PnmFileRetrieval")
            if not isinstance(pnm_file_retrieval, dict):
                self.logger.error("Missing or invalid 'PnmFileRetrieval' section in %s", config_path)
                return False

            retrieval_method = pnm_file_retrieval.get("retrieval_method")
            if not isinstance(retrieval_method, dict):
                legacy = pnm_file_retrieval.get("retrival_method")
                if isinstance(legacy, dict):
                    retrieval_method = legacy
                    pnm_file_retrieval["retrieval_method"] = retrieval_method
                    pnm_file_retrieval.pop("retrival_method", None)
                else:
                    self.logger.error("Missing or invalid 'retrieval_method' section in %s", config_path)
                    return False

            methods = retrieval_method.get("methods")
            if not isinstance(methods, dict):
                self.logger.error("Missing or invalid 'methods' section in %s", config_path)
                return False

            scp_section = methods.get("scp")
            if not isinstance(scp_section, dict):
                self.logger.error("Missing or invalid 'scp' section in %s", config_path)
                return False

            scp_section["private_key_path"] = new_path
        except Exception as exc:
            self.logger.error("Failed to update SCP private_key_path in %s: %s", config_path, exc)
            return False

        try:
            with open(config_path, "w", encoding = "utf-8") as f:
                json.dump(data, f, indent = 4)
                f.write("\n")
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", config_path, exc)
            return False

        return True

    def _update_system_json_sftp_private_key_path(self, config_path: str, new_path: str) -> bool:
        """
        Update The SFTP private_key_path In The System Configuration JSON.

        This function reads the JSON configuration file at config_path,
        updates only the PnmFileRetrieval.retrieval_method.methods.sftp
        .private_key_path field, and writes the file back to disk.
        """
        if not os.path.exists(config_path):
            self.logger.error("Configuration file not found: %s", config_path)
            return False

        try:
            with open(config_path, "r", encoding = "utf-8") as f:
                data: dict[str, object] = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.error("Failed to read %s: %s", config_path, exc)
            return False

        try:
            pnm_file_retrieval = data.get("PnmFileRetrieval")
            if not isinstance(pnm_file_retrieval, dict):
                self.logger.error("Missing or invalid 'PnmFileRetrieval' section in %s", config_path)
                return False

            retrieval_method = pnm_file_retrieval.get("retrieval_method")
            if not isinstance(retrieval_method, dict):
                legacy = pnm_file_retrieval.get("retrival_method")
                if isinstance(legacy, dict):
                    retrieval_method = legacy
                    pnm_file_retrieval["retrieval_method"] = retrieval_method
                    pnm_file_retrieval.pop("retrival_method", None)
                else:
                    self.logger.error("Missing or invalid 'retrieval_method' section in %s", config_path)
                    return False

            methods = retrieval_method.get("methods")
            if not isinstance(methods, dict):
                self.logger.error("Missing or invalid 'methods' section in %s", config_path)
                return False

            sftp_section = methods.get("sftp")
            if not isinstance(sftp_section, dict):
                self.logger.error("Missing or invalid 'sftp' section in %s", config_path)
                return False

            sftp_section["private_key_path"] = new_path
        except Exception as exc:
            self.logger.error("Failed to update SFTP private_key_path in %s: %s", config_path, exc)
            return False

        try:
            with open(config_path, "w", encoding = "utf-8") as f:
                json.dump(data, f, indent = 4)
                f.write("\n")
        except OSError as exc:
            self.logger.error("Failed to write %s: %s", config_path, exc)
            return False

        return True

    def _add_public_key_to_local_authorized_keys(self, public_key_path: str) -> bool:
        """
        Add The Public Key To The Local ~/.ssh/authorized_keys File.

        Ensures that ~/.ssh exists, creates authorized_keys if needed,
        and appends the public key only if it is not already present.
        """
        expanded_pub_path = os.path.expanduser(public_key_path)
        if not os.path.exists(expanded_pub_path):
            self.logger.error("Public key file not found: %s", expanded_pub_path)
            return False

        try:
            with open(expanded_pub_path, "r", encoding = "utf-8") as f:
                key = f.read().strip()
        except OSError as exc:
            self.logger.error("Failed to read public key file '%s': %s", expanded_pub_path, exc)
            return False

        if not key:
            self.logger.error("Public key file '%s' is empty.", expanded_pub_path)
            return False

        ssh_dir        = os.path.expanduser("~/.ssh")
        auth_keys_path = os.path.join(ssh_dir, "authorized_keys")

        try:
            os.makedirs(ssh_dir, mode = 0o700, exist_ok = True)
        except OSError as exc:
            self.logger.error("Failed to ensure ~/.ssh directory exists: %s", exc)
            return False

        if os.path.exists(auth_keys_path):
            try:
                with open(auth_keys_path, "r", encoding = "utf-8") as f:
                    existing = f.read()
                if key in existing:
                    self.logger.info("Public key already present in local authorized_keys.")
                    return True
            except OSError as exc:
                self.logger.error("Failed to read existing authorized_keys: %s", exc)
                return False

        try:
            new_file = not os.path.exists(auth_keys_path) or os.path.getsize(auth_keys_path) == 0
            with open(auth_keys_path, "a", encoding = "utf-8") as f:
                if new_file:
                    f.write(f"{key}\n")
                else:
                    f.write(f"\n{key}\n")
            os.chmod(auth_keys_path, 0o600)
        except OSError as exc:
            self.logger.error("Failed to update local authorized_keys: %s", exc)
            return False

        return True

    def _print_public_key_summary(self, public_key_path: str, private_key_path: str) -> None:
        """
        Print A Summary Of The Configured SSH Key Pair And Public Key Contents.

        Shows the resolved private/public key paths and dumps the public key
        so it can be copied into other systems if needed.
        """
        expanded_private = os.path.expanduser(private_key_path)
        expanded_public  = os.path.expanduser(public_key_path)

        self.logger.info("")
        self.logger.info("SSH key configuration summary:")
        self.logger.info("  Private key: %s", expanded_private)
        self.logger.info("  Public key:  %s", expanded_public)

        if not os.path.exists(expanded_public):
            self.logger.error("Public key file not found; cannot display contents: %s", expanded_public)
            return

        try:
            with open(expanded_public, "r", encoding = "utf-8") as f:
                key = f.read().strip()
        except OSError as exc:
            self.logger.error("Failed to read public key file '%s': %s", expanded_public, exc)
            return

        if not key:
            self.logger.error("Public key file '%s' is empty; nothing to display.", expanded_public)
            return

        print("")
        print("----- BEGIN PyPNM Public Key -----")
        print(key)
        print("----- END PyPNM Public Key -----")
        print("")

    def _prompt_yes_no(self, message: str) -> bool:
        """
        Prompt The User For A Yes/No Response.

        Returns True only if the user explicitly answers 'y' or 'Y'.
        """
        while True:
            answer = input(f"{message} [y/N]: ").strip()
            if answer.lower() == "y":
                return True
            if answer == "" or answer.lower() == "n":
                return False
            print("Please answer 'y' or 'n'.")


def main() -> None:
    """
    Entry Point For The SCP Key Setup Helper.
    """
    setup = ScpKeySetup()
    setup.run()


if __name__ == "__main__":
    main()
