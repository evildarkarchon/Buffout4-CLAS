import logging
import shutil
from collections.abc import Generator
from pathlib import Path

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
)


@pytest.fixture(scope="session", autouse=True)
def _move_user_files() -> Generator[None]:
    """Automatically moves all of CLASSIC's runtime-generated files into `test_temp/` during testing and restores them after.

    Any files created during testing are deleted.
    """
    temp_path = Path("test_temp")
    temp_path.mkdir(exist_ok=True)
    assert temp_path.is_dir(), f"Failed to create {temp_path}"
    assert not any(temp_path.iterdir()), f"{temp_path} is not empty"
    for file in RUNTIME_FILES:
        file_path = Path(file)
        backup_path = temp_path / file_path
        if file_path.exists():
            if len(file_path.parts) > 1:
                backup_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.rename(backup_path)
            assert backup_path.exists(), f"Failed to move {file_path} to {backup_path}"
        assert not file_path.exists(), f"Failed to remove {file_path}"
    yield
    for file in RUNTIME_FILES:
        file_path = Path(file)
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            shutil.rmtree(file_path)
        backup_path = temp_path / file_path
        if backup_path.exists():
            backup_path.rename(file_path)
            assert file_path.exists(), f"Failed to move {backup_path} to {file_path}"
        assert not backup_path.exists(), f"Failed to remove {backup_path}"
    for current, dirs, files in temp_path.walk(top_down=False):
        assert not files, f"{current} has unexpected new files"
        for d in dirs:
            subdir = current / d
            assert not any(subdir.iterdir()), f"{subdir} has unexpected contents"
            subdir.rmdir()
            assert not subdir.exists(), f"Failed to delete {subdir}"
    temp_path.rmdir()
    assert not temp_path.exists(), f"Failed to delete {temp_path}"


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
def _test_configure_logging(_move_user_files: None) -> Generator[None]:
    """Test CLASSIC_Main's `configure_logging()` and make its logger available during testing."""
    log_path = Path("CLASSIC Journal.log")
    assert not log_path.is_file(), f"{log_path} existed before testing"
    assert "CLASSIC" not in logging.Logger.manager.loggerDict, "Logger configured before testing"
    return_value = CLASSIC_Main.configure_logging()  # type: ignore[func-returns-value]
    assert return_value is None, "configure_logging() unexpectedly returned a value"
    assert CLASSIC_Main.logger.name == "CLASSIC", "A logger named CLASSIC was not configured"
    assert log_path.is_file(), f"{log_path} was not created"
    CLASSIC_Main.logger.info("Logger test")
    yield
    for h in CLASSIC_Main.logger.handlers:
        if isinstance(h, logging.FileHandler):
            h.close()
    assert log_path.stat().st_size > 0, "Log file was not written to"
