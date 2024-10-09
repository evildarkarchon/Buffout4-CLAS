import stat
from collections.abc import Generator
from pathlib import Path

import pytest

import CLASSIC_Main


@pytest.fixture
def test_file() -> Generator[Path]:
    test_file_path = Path("tests/test_file.txt")
    test_file_path.touch(exist_ok=True)
    assert test_file_path.is_file()
    yield test_file_path
    test_file_path.unlink(missing_ok=True)


def test_remove_readonly(test_file: Path) -> None:
    test_file.chmod(~stat.S_IWRITE)
    assert test_file.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 1
    CLASSIC_Main.remove_readonly(test_file)
    assert test_file.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 0
