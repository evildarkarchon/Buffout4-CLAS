from pathlib import Path

import pytest
from requests import HTTPError

import CLASSIC_ScanLogs


def test_pastebin_fetch() -> None:
    """Test CLASSIC_ScanLogs's `pastebin_fetch()`."""
    test_url = "https://pastebin.com/7rXpAw8s"
    test_url_fake = "https://pastebin.com/XXXXXXXX"
    pastebin_path = Path("CLASSIC Pastebin")

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


def test_get_entry() -> None:
    """Test CLASSIC_ScanLogs's `get_entry()`."""


def test_crashlogs_get_files() -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_get_files()`."""


def test_crashlogs_reformat() -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_reformat()`."""


def test_crashlogs_scan() -> None:
    """Test CLASSIC_ScanLogs's `crashlogs_scan()`."""
