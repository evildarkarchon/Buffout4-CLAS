from pathlib import Path

import pytest
from requests import HTTPError

import CLASSIC_ScanLogs
from tests.conftest import MockYAML


def test_pastebin_fetch() -> None:
    """Test CLASSIC_ScanLogs's `pastebin_fetch()`."""
    test_url = "https://pastebin.com/7rXpAw8s"
    test_url_fake = "https://pastebin.com/XXXXXXXX"
    pastebin_path = Path("Crash Logs/Pastebin")

    assert not pastebin_path.exists(), f"{pastebin_path} existed before testing"

    # Test failed request
    pytest.raises(HTTPError, CLASSIC_ScanLogs.pastebin_fetch, url=test_url_fake)

    return_value = CLASSIC_ScanLogs.pastebin_fetch(url=test_url)  # type: ignore[func-returns-value]
    assert return_value is None, "pastebin_fetch() unexpectedly returned a value"

    assert pastebin_path.is_dir(), f"{pastebin_path} was not created"
    contents = list(pastebin_path.glob("*"))
    assert len(contents) > 0, f"Fetched crash log was not saved to {pastebin_path}"
    assert len(contents) == 1, f"More than one file was created in {pastebin_path}"
    assert contents[0].name.startswith("crash-"), "Created file not prefixed with `crash-`"
    assert contents[0].suffix == ".log", "Created file doesn't have the extension `.log`"
    assert contents[0].stat().st_size > 0, "Created file is empty"


@pytest.mark.usefixtures("_gamevars")
def test_get_entry() -> None:
    """Test CLASSIC_ScanLogs's `get_entry()`."""
    #- Form ID: 0000003C | [Fallout4.esm] | Commonwealth | 2
    game = "Fallout4"
    db_path_main = Path(f"CLASSIC Data/databases/{game} FormIDs Main.db")
    db_path_local = Path(f"CLASSIC Data/databases/{game} FormIDs Local.db")
    db_found = db_path_main.is_file() and db_path_local.is_file()
    assert db_found is True, "DB files not found"

    test_formid = "00003C"
    test_plugin = "Fallout4.esm"

    assert db_path_main.is_file(), f"{db_path_main} does not exist"
    assert db_path_local.is_file(), f"{db_path_local} does not exist"
    assert isinstance(CLASSIC_ScanLogs.query_cache, dict), "query_cache is expected to be a dict"
    return_value_1 = CLASSIC_ScanLogs.get_entry("FFFFFF", "XXXXXXXX.esm")
    assert return_value_1 is None, "get_entry() should return None when no entry found"

    initial_cache_size = len(CLASSIC_ScanLogs.query_cache)
    return_value_2 = CLASSIC_ScanLogs.get_entry(test_formid, test_plugin)
    assert return_value_2 is not None, f"get_entry() should always find {test_plugin} FormIDs"
    assert isinstance(return_value_2, str), "get_entry() should return str"
    assert len(CLASSIC_ScanLogs.query_cache) == initial_cache_size + 1, "query_cache size did not increase by 1"
    cache_key = next(k for k in CLASSIC_ScanLogs.query_cache)
    assert isinstance(cache_key, tuple), "query_cache keys are expected to be tuple"
    assert len(cache_key) == 2, "query_cache keys are expected to be tuple of length 2"
    assert all(isinstance(v, str) for v in cache_key), "query_cache keys are expected to contain only str"
    assert CLASSIC_ScanLogs.query_cache.get((test_formid, test_plugin)) == return_value_2, "result not found in query_cache"

    return_value_3 = CLASSIC_ScanLogs.get_entry(test_formid, test_plugin)
    assert return_value_3 == return_value_2, "get_entry() should return the previously cached value"
    assert len(CLASSIC_ScanLogs.query_cache) == initial_cache_size + 1, "query_cache size should not have increased for repeated query"


@pytest.mark.usefixtures("_gamevars")
def test_crashlogs_get_files(mock_yaml: MockYAML) -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_get_files()`."""
    CLASSIC_logs = Path.cwd() / "Crash Logs"

    mock_yaml["Docs_Folder_XSE"] = "tests/"
    mock_yaml["SCAN Custom Path"] = "tests/"

    test_logs = [
        Path.cwd() / "tests/crash-TEST_1.log",
        Path.cwd() / "tests/crash-TEST_2.log",
    ]
    for f in test_logs:
        copy_destination = CLASSIC_logs / f.name
        assert not copy_destination.exists(), f"{copy_destination} existed before testing"
        f.touch()
        assert f.is_file(), f"{f} was not created"

    return_value = CLASSIC_ScanLogs.crashlogs_get_files()
    assert isinstance(return_value, list), "crashlogs_get_files() is expected to return a list"
    assert len(return_value) == 4, "crashlogs_get_files() is expected to find 4 test logs"
    assert all(r.name.startswith("crash-TEST_") for r in return_value), "Non-test logs were included in results"

    for q in test_logs:
        copy_destination = CLASSIC_logs / q.name
        assert copy_destination.exists(), f"{q.name} was not copied to CLASSIC's folder"
    for s in return_value:
        s.unlink(missing_ok=True)
        assert not s.exists(), f"{s} was not deleted"


def test_crashlogs_reformat() -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_reformat()`."""


def test_crashlogs_scan() -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_scan()`."""
