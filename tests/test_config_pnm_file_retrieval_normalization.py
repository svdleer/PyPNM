# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pypnm.config.config_manager import ConfigManager
from pypnm.config.system_config_settings import SystemConfigSettings


class FakeConfigManager:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self._data = data or {}

    def get(self, *path: str) -> object | None:
        key = ".".join(path)
        return self._data.get(key)


def test_config_manager_accepts_legacy_retrival_method(tmp_path: Path) -> None:
    payload = {
        "PnmFileRetrieval": {
            "retrival_method": {
                "method": "tftp",
                "methods": {},
            },
        },
    }
    config_path = tmp_path / "system.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = ConfigManager(config_path=str(config_path))

    assert cfg.get("PnmFileRetrieval", "retrieval_method", "method") == "tftp"


def test_config_manager_prefers_retrieval_method(tmp_path: Path) -> None:
    payload = {
        "PnmFileRetrieval": {
            "retrieval_method": {
                "method": "sftp",
                "methods": {},
            },
            "retrival_method": {
                "method": "tftp",
                "methods": {},
            },
        },
    }
    config_path = tmp_path / "system.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    cfg = ConfigManager(config_path=str(config_path))

    assert cfg.get("PnmFileRetrieval", "retrieval_method", "method") == "sftp"


def test_empty_tftp_remote_dir_does_not_log_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeConfigManager(
        {
            "PnmFileRetrieval.retrieval_method.methods.tftp.remote_dir": "",
        }
    )
    monkeypatch.setattr(SystemConfigSettings, "_cfg", fake)

    logger_name = "SystemConfigSettings"
    with caplog.at_level(logging.ERROR, logger=logger_name):
        value = SystemConfigSettings.tftp_remote_dir()

    assert value == ""
    assert caplog.text == ""


def test_missing_tftp_remote_dir_does_not_log_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeConfigManager()
    monkeypatch.setattr(SystemConfigSettings, "_cfg", fake)

    logger_name = "SystemConfigSettings"
    with caplog.at_level(logging.ERROR, logger=logger_name):
        value = SystemConfigSettings.tftp_remote_dir()

    assert value == ""
    assert caplog.text == ""
