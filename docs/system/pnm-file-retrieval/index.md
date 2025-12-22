# PyPNM File Retrieval Methods

PyPNM supports multiple methods for retrieving files necessary for its operation. These methods provide flexibility depending on the deployment environment and security requirements.

| Method | Description |
|---------|------------|
| [Local](local.md) | Guide to setting local file retrieval where PyPNM is the TFTP server.          |
| [TFTP](tftp.md)   | Guide to configuring TFTP file retrieval from a remote PNM TFTP server.        |
| [SFTP](sftp.md)   | Guide to setting up SFTP file retrieval using SSH keys / password for PyPNM.   |
| [SCP key setup helper](scp-key-setup-helper.md) | Prepares SSH keys/config for SCP or hybrid SCP/SFTP workflows. |

Need to change topology or method quickly? Use the interactive helper located at [`tools/pnm/pnm_file_retrieval_setup.py`](https://github.com/svdleer/PyPNM/blob/main/tools/pnm/pnm_file_retrieval_setup.py) to update `system.json` without editing by hand.
