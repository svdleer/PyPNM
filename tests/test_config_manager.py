# tests/test_config_manager.py
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2025 Maurice Garcia

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pypnm.config.config_manager import ConfigManager


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """
    Create A Temporary JSON Config File For Testing.

    The file is named ``system.json`` so it matches the default
    naming convention used by ConfigManager, but tests always
    pass the full explicit path into the constructor.
    """
    cfg_path = tmp_path / "system.json"
    data = {
        "database": {
            "host": "localhost",
            "port": 5432,
        },
        "feature_flags": {
            "beta_mode": True,
        },
        "logging": {
            "level": "INFO",
        },
    }
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    return cfg_path


def test_init_with_explicit_path_loads_config(config_file: Path) -> None:
    """
    Verify That ConfigManager Loads JSON From The Provided Path.
    """
    mgr = ConfigManager(config_path=str(config_file))

    host = mgr.get("database", "host")
    port = mgr.get("database", "port")
    beta = mgr.get("feature_flags", "beta_mode")

    assert host == "localhost"
    assert port == 5432
    assert beta is True


def test_get_returns_fallback_when_key_missing(config_file: Path) -> None:
    """
    Ensure get() Returns The Fallback Value When Any Key Is Missing.
    """
    mgr = ConfigManager(config_path=str(config_file))

    value = mgr.get("does_not_exist", fallback="default-value")
    nested = mgr.get("database", "missing_key", fallback=123)

    assert value == "default-value"
    assert nested == 123


def test_get_returns_none_when_missing_and_no_fallback(config_file: Path) -> None:
    """
    Ensure get() Returns None When The Key Path Is Missing And No Fallback Is Provided.
    """
    mgr = ConfigManager(config_path=str(config_file))

    value = mgr.get("no_such_section")
    nested = mgr.get("logging", "no_such_key")

    assert value is None
    assert nested is None


def test_as_dict_returns_top_level_copy(config_file: Path) -> None:
    """
    Verify That as_dict() Returns A Top-Level Copy Of The Configuration.

    Mutating Top-Level Keys In The Returned Dict Must Not Affect The
    Internal State Stored By ConfigManager. Nested Objects Are Shared
    (Shallow Copy), Which Is Acceptable For The Current Implementation.
    """
    mgr = ConfigManager(config_path=str(config_file))

    cfg = mgr.as_dict()
    assert cfg["database"]["host"] == "localhost"

    # Rebind the top-level "database" entry in the copy
    cfg["database"] = {"host": "mutated-host", "port": 9999}

    # Internal manager state remains unchanged
    original_host = mgr.get("database", "host")
    original_port = mgr.get("database", "port")

    assert original_host == "localhost"
    assert original_port == 5432


def test_reload_re_reads_changes_from_disk(tmp_path: Path) -> None:
    """
    Verify That reload() Re-Loads Configuration From The Underlying File.
    """
    cfg_path = tmp_path / "system.json"

    initial = {"value": 1}
    cfg_path.write_text(json.dumps(initial), encoding="utf-8")

    mgr = ConfigManager(config_path=str(cfg_path))
    assert mgr.get("value") == 1

    updated = {"value": 2}
    cfg_path.write_text(json.dumps(updated), encoding="utf-8")

    mgr.reload()
    assert mgr.get("value") == 2


def test_save_overwrites_config_and_writes_to_disk(tmp_path: Path) -> None:
    """
    Ensure save() Updates In-Memory Config And Persists It To Disk.
    """
    cfg_path = tmp_path / "system.json"

    initial = {"value": 10, "nested": {"flag": False}}
    cfg_path.write_text(json.dumps(initial), encoding="utf-8")

    mgr = ConfigManager(config_path=str(cfg_path))
    assert mgr.get("value") == 10
    assert mgr.get("nested", "flag") is False

    new_cfg = {"value": 42, "nested": {"flag": True}}
    mgr.save(new_cfg)

    # In-memory state updated
    assert mgr.get("value") == 42
    assert mgr.get("nested", "flag") is True

    # On-disk state updated
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw == new_cfg


def test_init_raises_when_file_missing(tmp_path: Path) -> None:
    """
    Verify That Initializing With A Non-Existent Path Raises FileNotFoundError.
    """
    missing = tmp_path / "missing_system.json"
    with pytest.raises(FileNotFoundError):
        _ = ConfigManager(config_path=str(missing))
