#!/usr/bin/env python3
from __future__ import annotations

# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia


import json
import sys
from pathlib import Path
from typing import Any

from common import (
    JsonObject,
    JSON_INDENT_WIDTH,
    DEFAULT_CONFIG_PATH,
    SystemJsonEditorBase,
)


class PnmFileRetrievalEditor(SystemJsonEditorBase):
    """
    Interactive Editor For PnmFileRetrieval Retrieval Method.

    Only updates the 'retrieval_method.method' and the
    'retrieval_method.methods.local.src_dir' field. Directory paths,
    database paths, and retry counts are left unchanged.
    """

    def _section(self) -> JsonObject:
        section = self.data.get("PnmFileRetrieval")
        if not isinstance(section, dict):
            section = {}
            self.data["PnmFileRetrieval"] = section
        return section

    def run(self) -> int:
        """
        Run The Interactive PnmFileRetrieval Editor.

        Allows editing of the retrieval method and local src_dir only,
        then displays and commits the proposed changes when confirmed.
        """
        section = self._section()

        retrieval_method = section.get("retrieval_method")
        if not isinstance(retrieval_method, dict):
            legacy = section.get("retrival_method")
            if isinstance(legacy, dict):
                retrieval_method = legacy
            else:
                retrieval_method = {}
            section["retrieval_method"] = retrieval_method
            section.pop("retrival_method", None)

        methods = retrieval_method.get("methods")
        if not isinstance(methods, dict):
            methods = {}
            retrieval_method["methods"] = methods

        local = methods.get("local")
        if not isinstance(local, dict):
            local = {}
            methods["local"] = local

        print("Editing PnmFileRetrieval (retrieval_method only) in system.json\n")

        method_new = self.prompt_str(
            "Retrieval method (local | tftp | ftp | scp | sftp | http | https)",
            retrieval_method.get("method"),
        )
        local_src_new = self.prompt_str(
            "Local src_dir for 'local' method",
            local.get("src_dir"),
        )

        if method_new is None and local_src_new is None:
            print("No changes requested. Exiting without modification.")
            return 0

        if method_new is not None:
            retrieval_method["method"] = method_new
        if local_src_new is not None:
            local["src_dir"] = local_src_new

        print("\nProposed changes (subset of PnmFileRetrieval):")
        print(
            json.dumps(
                {
                    "PnmFileRetrieval": {
                        "retrieval_method": retrieval_method,
                    },
                },
                indent=JSON_INDENT_WIDTH,
            )
        )

        confirm = input("\nApply these changes? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Changes discarded.")
            return 0

        self._save()
        print(f"Updated {self.config_path}")
        return 0


def main() -> int:
    """
    Main Entry Point For The PnmFileRetrieval Editor.

    Prompts for the configuration path and runs the interactive editor
    for the PnmFileRetrieval retrieval settings.
    """
    config_path = SystemJsonEditorBase.prompt_config_path(DEFAULT_CONFIG_PATH)
    editor      = PnmFileRetrievalEditor(config_path)
    return editor.run()


if __name__ == "__main__":
    raise SystemExit(main())
