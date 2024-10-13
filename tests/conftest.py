import shutil
from collections.abc import Generator
from pathlib import Path
from typing import TypeAliasType, get_args

import pytest

import CLASSIC_Main

RUNTIME_FILES = (
    "CLASSIC Settings.yaml",
    "CLASSIC Ignore.yaml",
    "CLASSIC Journal.log",
    "CLASSIC Data/CLASSIC Data.zip",
    "CLASSIC Data/CLASSIC Fallout4 Local.yaml",
    "CLASSIC Data/CLASSIC Skyrim Local.yaml",
    "CLASSIC Data/CLASSIC Starfield Local.yaml",
    "CLASSIC Backup",
    "CLASSIC Pastebin",
)


@pytest.fixture(scope="session", autouse=True)
def _move_user_files() -> Generator[None]:
    """Automatically moves all of CLASSIC's runtime-generated files into `test_temp/` during testing and restores them after.

    Any files created during testing are deleted.
    """
    for file in RUNTIME_FILES:
        file_path = Path(file)
        if file_path.exists():
            backup_path = file_path.with_name(f"test_temp-{file_path.name}")
            file_path.rename(backup_path)
            assert backup_path.exists(), f"Failed to rename {file_path.name} to {backup_path.name}"
        assert not file_path.exists(), f"Failed to rename {file_path.name}"

    yield

    for file in RUNTIME_FILES:
        file_path = Path(file)
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            shutil.rmtree(file_path)
        backup_path = file_path.with_name(f"test_temp-{file_path.name}")
        if backup_path.exists():
            backup_path.rename(file_path)
            assert file_path.exists(), f"Failed to rename {backup_path.name} to {file_path.name}"
        assert not backup_path.exists(), f"Failed to remove {backup_path.name}"


@pytest.fixture(scope="session")
def yaml_cache() -> CLASSIC_Main.YamlSettingsCache:
    """Initialize CLASSIC_Main's YAML Cache.

    This is required for any test that entails calls to:
    - `yaml_settings()`
    - `get_setting()`
    - `classic_settings()`
    """
    CLASSIC_Main.yaml_cache = CLASSIC_Main.YamlSettingsCache()
    assert isinstance(CLASSIC_Main.yaml_cache.cache, dict), "cache dict not created"
    assert isinstance(CLASSIC_Main.yaml_cache.file_mod_times, dict), "file_mod_times dict not created"
    return CLASSIC_Main.yaml_cache


@pytest.fixture(scope="session")
def _gamevars() -> None:
    """Ensure CLASSIC_Main's gamevars global is initialized and validate its types."""
    assert isinstance(CLASSIC_Main.gamevars, dict), "CLASSIC_Main.gamevars should be initialized to dict"
    assert len(CLASSIC_Main.gamevars) > 0, "CLASSIC_Main.gamevars should contain default values"
    assert isinstance(CLASSIC_Main.GameID, TypeAliasType), "CLASSIC_Main.GameID type is unexpected"
    assert (
        CLASSIC_Main.GameVars.__annotations__["game"] is CLASSIC_Main.GameID
    ), "CLASSIC_Main.GameVars type is unexpected"
    game_ids = get_args(CLASSIC_Main.GameVars.__annotations__["game"].__value__)
    vr_values = get_args(CLASSIC_Main.GameVars.__annotations__["vr"])
    assert len(game_ids) > 0, "CLASSIC_Main.GameID type is unexpected"
    assert all(isinstance(g, str) for g in game_ids), "CLASSIC_Main.GameID type is unexpected"
    assert CLASSIC_Main.gamevars.get("game") in game_ids, "CLASSIC_Main.gamevars['game'] not initialized"
    assert CLASSIC_Main.gamevars.get("vr") in vr_values, "CLASSIC_Main.gamevars['vr'] not initialized"
