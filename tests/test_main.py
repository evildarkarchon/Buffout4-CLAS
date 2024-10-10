import binascii
import datetime
import os
import random
import shutil
import stat
import string
from collections.abc import Generator
from pathlib import Path
from typing import TypeAliasType, get_args

import pytest
import ruamel.yaml

import CLASSIC_Main

LATEST_VERSION = "CLASSIC v7.30.2"

TEST_YAML_TEXT = """Section 1:
  Game Name: Elder Scrolls VI
  False Bool: false
  True Bool: true
  Positive Int: 8675309
  Negative Int: -404
  Positive Float: 3.14159
  Negative Float: -6.66
  List of Str:
    - Monday
    - Tuesday
    - Wednesday
    - Thursday
    - Friday
    - Saturday
    - Sunday
  Alt Syntax List of Int: [3, 6, 9]
  Dict of Str:
    BA2 Limit Crash: LooseFileAsyncStream
    DLL Crash: DLCBannerDLC01.dds
Section 2:
  Str Write:
  Int Write:
  Bool Write:
  Dict Write:
  List Write:
"""

# Hex for an uncompressed zip containing an empty `databases/CLASSIC Main.yaml`
# To recreate file: `with open("f.zip", "wb") as f: f.write(binascii.unhexlify(TEST_ZIP))`
TEST_ZIP = (
    "504B03041400000000004CA749590000000000000000000000000A0000006461746162617365732F504B03040A0000000000"
    "38A749590000000000000000000000001B0000006461746162617365732F434C4153534943204D61696E2E79616D6C504B01"
    "023F001400000000004CA749590000000000000000000000000A002400000000000000100000000000000064617461626173"
    "65732F0A0020000000000001001800A881BA81AF1ADB0100000000000000000000000000000000504B01023F000A00000000"
    "0038A749590000000000000000000000001B00240000000000000020000000280000006461746162617365732F434C415353"
    "4943204D61696E2E79616D6C0A002000000000000100180057E1A06BAF1ADB0100000000000000000000000000000000504B"
    "05060000000002000200C9000000610000000000"
)

# Hex for a UTF-16 encoded text file containing "śÛ"
TEST_UTF16LE = "FFFE5B01DB00"

TEST_F4SE_LOG = r"""plugin directory = tests\Data\F4SE\Plugins\
scanning plugin directory tests\Fallout 4\Data\F4SE\Plugins\
"""


@pytest.fixture
def _move_data_files() -> Generator[None]:
    """Rename `CLASSIC Data/` to `test_temp-CLASSIC Data/` during testing and restores it after.

    Any files created during testing are deleted.
    """
    data_path = Path("CLASSIC Data")
    backup_path = Path("test_temp-CLASSIC Data")
    assert data_path.is_dir(), f"{data_path} does not exist"
    assert not backup_path.exists(), f"{backup_path} existed before testing"
    data_path.rename(backup_path)
    assert not data_path.is_dir(), f"{data_path} was not renamed"
    assert backup_path.exists(), f"{backup_path} was not created"
    yield
    assert backup_path.is_dir(), f"{backup_path} was deleted by another process or test"
    shutil.rmtree(data_path)
    assert not data_path.is_dir(), f"{data_path} was not deleted"
    backup_path.rename(data_path)
    assert not backup_path.exists(), f"{backup_path} was not renamed"
    assert data_path.is_dir(), f"{data_path} was not created"


@pytest.fixture
def _gamevars() -> None:
    """Initialize CLASSIC_Main's gamevars global and validate its types."""
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


@pytest.fixture
def test_file_text() -> Generator[Path]:
    """Create an empty file `tests/test_file.txt` for the duration of the test."""
    test_file_path = Path("tests/test_file.txt")
    test_file_path.touch(exist_ok=True)
    assert test_file_path.is_file(), f"failed to create {test_file_path}"
    yield test_file_path
    if test_file_path.exists():
        test_file_path.chmod(stat.S_IWRITE)
        test_file_path.unlink(missing_ok=True)
    assert not test_file_path.exists(), f"failed to delete {test_file_path}"


@pytest.fixture(scope="module")
def test_file_yaml() -> Generator[Path]:
    """Create a test YAML file `tests/test_settings.yaml` containing `TEST_YAML_TEXT` for the duration of the test."""
    test_file_path = Path("tests/test_settings.yaml")
    with test_file_path.open("w") as f:
        f.write(TEST_YAML_TEXT)
    assert test_file_path.is_file(), f"failed to create {test_file_path}"
    yield test_file_path
    test_file_path.unlink(missing_ok=True)
    assert not test_file_path.exists(), f"failed to delete {test_file_path}"


def test_remove_readonly(test_file_text: Path) -> None:
    """Test CLASSIC_Main's `remove_readonly()`."""
    # Test without read-only
    assert (
        test_file_text.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 0
    ), f"{test_file_text} should NOT be read-only"
    return_value = CLASSIC_Main.remove_readonly(test_file_text)  # type: ignore[func-returns-value]
    assert return_value is None, "remove_readonly() unexpectedly returned a value"
    assert (
        test_file_text.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 0
    ), f"{test_file_text} should NOT be read-only"

    # Test with read-only
    test_file_text.chmod(~stat.S_IWRITE)
    assert (
        test_file_text.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 1
    ), f"{test_file_text} should be read-only"
    return_value = CLASSIC_Main.remove_readonly(test_file_text)  # type: ignore[func-returns-value]
    assert return_value is None, "remove_readonly() unexpectedly returned a value"
    assert (
        test_file_text.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 0
    ), f"{test_file_text} should NOT be read-only"

    # Test with missing file
    test_file_text.unlink(missing_ok=True)
    assert not test_file_text.exists(), f"failed to delete {test_file_text}"
    return_value = CLASSIC_Main.remove_readonly(test_file_text)  # type: ignore[func-returns-value]
    assert return_value is None, "remove_readonly() unexpectedly returned a value"


@pytest.fixture(scope="module")
def test_load_yaml(test_file_yaml: Path, yaml_cache: CLASSIC_Main.YamlSettingsCache) -> CLASSIC_Main.YamlSettingsCache:
    """Test CLASSIC_Main's `YamlSettingsCache`.`load_yaml()`."""
    fake_path = Path("Non-existant file")
    loaded_data_1 = yaml_cache.load_yaml(fake_path)
    assert isinstance(loaded_data_1, dict), "load_yaml() should always return a dict"
    assert len(loaded_data_1) == 0, "load_yaml() should return an empty dict for non-existant files"
    assert yaml_cache.cache.get(fake_path) is None, "load_yaml() should not cache for non-existant files"
    loaded_data_2 = yaml_cache.load_yaml(test_file_yaml)
    assert isinstance(loaded_data_2, dict), "load_yaml() should always return a dict"
    assert len(yaml_cache.cache) > 0, "no data loaded into yaml_cache"
    assert yaml_cache.cache[test_file_yaml] == loaded_data_2, "load_yaml() should cache the returned dict"
    return yaml_cache


def test_YamlSettingsCache_get_setting(test_file_yaml: Path, test_load_yaml: CLASSIC_Main.YamlSettingsCache) -> None:
    """Test CLASSIC_Main's `YamlSettingsCache`.`get_setting()`."""
    game = test_load_yaml.get_setting(test_file_yaml, "Section 1.Game Name")
    assert isinstance(game, str), "Section 1.Game Name should be a string"
    assert game == "Elder Scrolls VI", "Section 1.Game Name should equal 'Elder Scrolls VI'"

    bool_false = test_load_yaml.get_setting(test_file_yaml, "Section 1.False Bool")
    assert bool_false is False, "Section 1.False Bool should be False"

    bool_true = test_load_yaml.get_setting(test_file_yaml, "Section 1.True Bool")
    assert bool_true is True, "Section 1.True Bool should be True"

    int_positive = test_load_yaml.get_setting(test_file_yaml, "Section 1.Positive Int")
    assert isinstance(int_positive, int), "Section 1.Positive Int should be int"
    assert int_positive == 8675309, "Section 1.Positive Int should equal 8675309"

    int_negative = test_load_yaml.get_setting(test_file_yaml, "Section 1.Negative Int")
    assert isinstance(int_negative, int), "Section 1.Negative Int should be int"
    assert int_negative == -404, "Section 1.Negative Int should equal -404"

    float_positive = test_load_yaml.get_setting(test_file_yaml, "Section 1.Positive Float")
    assert isinstance(float_positive, float), "Section 1.Positive Float should be float"
    assert float_positive == 3.14159, "Section 1.Positive Int Float equal 3.14159"

    float_negative = test_load_yaml.get_setting(test_file_yaml, "Section 1.Negative Float")
    assert isinstance(float_negative, float), "Section 1.Negative Float should be float"
    assert float_negative == -6.66, "Section 1.Negative Float should equal -6.66"

    list_of_str = test_load_yaml.get_setting(test_file_yaml, "Section 1.List of Str")
    assert isinstance(list_of_str, list), "Section 1.List of Str should be list"
    assert all(isinstance(s, str) for s in list_of_str), "Section 1.List of Str should contain only str"
    assert len(list_of_str) == 7, "Section 1.List of Str length should be 7"
    assert list_of_str[1] == "Tuesday", "Section 1.List of Str index 1 should equal 'Tuesday'"

    alt_list_of_int = test_load_yaml.get_setting(test_file_yaml, "Section 1.Alt Syntax List of Int")
    assert isinstance(alt_list_of_int, list), "Section 1.Alt Syntax List of Int should be list"
    assert all(isinstance(i, int) for i in alt_list_of_int), "Section 1.Alt Syntax List of Int should contain only int"
    assert len(alt_list_of_int) == 3, "Section 1.Alt Syntax List of Int length should be 3"
    assert alt_list_of_int[-1] == 9, "Section 1.Alt Syntax List of Int index -1 should equal 9"

    dict_of_str = test_load_yaml.get_setting(test_file_yaml, "Section 1.Dict of Str")
    assert isinstance(dict_of_str, dict), "Section 1.Dict of Str should be dict"
    assert all(isinstance(i, str) for i in dict_of_str), "Section 1.Dict of Str should contain only str:str"
    assert len(dict_of_str) == 2, "Section 1.Dict of Str length should be 2"
    assert (
        dict_of_str["BA2 Limit Crash"] == "LooseFileAsyncStream"
    ), "Section 1.Dict of Str index 'BA2 Limit Crash' should equal 'LooseFileAsyncStream'"
    assert (
        dict_of_str.get("Non-existant") is None
    ), "Section 1.Dict of Str get() for non-existent value should return None"

    printable_characters = list(string.printable)
    random.shuffle(printable_characters)
    random_string = "".join(printable_characters + list(reversed(printable_characters)))
    return_string_1 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Str Write", random_string)
    assert return_string_1 == random_string, "get_setting() should return the new str value"
    return_string_2 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Str Write")
    assert return_string_2 == random_string, "get_setting() should return the str value exactly as written"

    random_int = random.randint(-255, 255)
    return_int_1 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Int Write", random_int)  # type: ignore
    assert return_int_1 == random_int, "get_setting() should return the new int value"
    return_int_2 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Int Write")
    assert return_int_2 == random_int, "get_setting() should return the int value exactly as written"

    random_bool = random.random() < 0.5
    return_bool_1 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Bool Write", random_bool)
    assert return_bool_1 is random_bool, "get_setting() should return the new bool value"
    return_bool_2 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Bool Write")
    assert return_bool_2 is random_bool, "get_setting() should return the bool value exactly as written"

    random_dict = {
        random_string: random_string.swapcase(),
        random_int: random_bool,
        "Three": 3,
    }
    return_dict_1 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Dict Write", random_dict)  # type: ignore
    assert isinstance(return_dict_1, dict), "get_setting() should return the new dict value"
    assert return_dict_1 == random_dict, "get_setting() should return the dict value exactly as written"
    return_dict_2 = test_load_yaml.get_setting(test_file_yaml, "Section 2.Dict Write")
    assert isinstance(return_dict_2, dict), "get_setting() should return the new dict value"
    assert return_dict_2 == random_dict, "get_setting() should return the dict value exactly as written"
    assert list(random_dict.keys()) == list(
        return_dict_2.keys()
    ), "get_setting() should return the dict value exactly as written"

    random_list = random.choices(string.printable, k=6) + random.choices((0, 1, 2, 3, 4, 5, 6, 7, 8, 9), k=4)
    return_list_1 = test_load_yaml.get_setting(test_file_yaml, "Section 2.List Write", random_list)  # type: ignore
    assert isinstance(return_list_1, list), "get_setting() should return the new list value"
    assert return_list_1 == random_list, "get_setting() should return the list value exactly as written"
    return_list_2 = test_load_yaml.get_setting(test_file_yaml, "Section 2.List Write")
    assert isinstance(return_list_2, list), "get_setting() should return the new list value"
    assert return_list_2 == random_list, "get_setting() should return the list value exactly as written"
    assert (
        isinstance(v, type(random_list[i])) for i, v in enumerate(return_list_2)
    ), "get_setting() should return the list value exactly as written"


def test_yaml_settings(test_file_yaml: Path, test_load_yaml: CLASSIC_Main.YamlSettingsCache) -> None:
    """Test CLASSIC_Main's `yaml_settings()`."""
    assert isinstance(test_load_yaml, CLASSIC_Main.YamlSettingsCache), "yaml cache should be initialized"
    game = CLASSIC_Main.yaml_settings(str(test_file_yaml), "Section 1.Game Name")
    assert isinstance(game, str), "Section 1.Game Name should be a string"
    assert game == "Elder Scrolls VI", "Section 1.Game Name should equal 'Elder Scrolls VI'"


@pytest.mark.usefixtures("_move_user_files", "yaml_cache")
def test_classic_settings() -> None:
    """Test CLASSIC_Main's `classic_settings()`."""
    settings_path = Path("CLASSIC Settings.yaml")
    return_value = CLASSIC_Main.classic_settings()
    assert return_value is None, "classic_settings() should return None when no setting is specified"
    assert settings_path.is_file(), f"Failed to create {settings_path}"
    update_check = CLASSIC_Main.classic_settings("Update Check")
    assert update_check is True or update_check is False, "update_check must be bool"


@pytest.mark.usefixtures("_move_user_files", "_gamevars", "yaml_cache")
def test_classic_generate_files() -> None:
    """Test CLASSIC_Main's `classic_generate_files()`."""
    ignore_path = Path("CLASSIC Ignore.yaml")
    local_path = Path(f"CLASSIC Data/CLASSIC {CLASSIC_Main.gamevars["game"]} Local.yaml")
    assert not ignore_path.exists(), f"{ignore_path} existed before testing"
    assert not local_path.exists(), f"{local_path} existed before testing"
    return_value = CLASSIC_Main.classic_generate_files()  # type: ignore[func-returns-value]
    assert return_value is None, "classic_generate_files() unexpectedly returned a value"
    assert ignore_path.is_file(), f"{ignore_path} was not created"
    assert local_path.is_file(), f"{local_path} was not created"
    ignore_path.unlink(missing_ok=True)
    local_path.unlink(missing_ok=True)
    assert not ignore_path.exists(), f"{local_path} was not deleted"
    assert not local_path.exists(), f"{local_path} was not deleted"


@pytest.mark.xfail(reason="Known issue to be fixed in PR", raises=AssertionError)
@pytest.mark.usefixtures("_move_user_files", "_test_configure_logging")
def test_classic_logging() -> None:
    """Test CLASSIC_Main's `classic_logging()`."""
    log_path = Path("CLASSIC Journal.log")
    assert log_path.is_file(), f"{log_path} does not exist"
    new_time = (datetime.datetime.now() - datetime.timedelta(days=8)).timestamp()
    os.utime(log_path, (new_time, new_time))
    assert log_path.stat().st_mtime == new_time, f"Timestamps not updated on {log_path}"
    CLASSIC_Main.classic_logging()
    assert log_path.stat().st_size == 0, f"{log_path} was not regenerated"


@pytest.fixture
def _move_zip_files() -> Generator[None]:
    """Rename any zip files named `CLASSIC Data.zip` for the duration of the test."""
    zip_path = Path("CLASSIC Data.zip")
    zipfiles = list(Path.cwd().rglob(str(zip_path), case_sensitive=False))

    for zipfile in zipfiles:
        zipfile.rename(zipfile.with_stem("test_temp"))

    yield

    for zipfile in zipfiles:
        zipfile.with_stem("test_temp").rename(zipfile)


@pytest.mark.usefixtures("_move_data_files", "_move_zip_files")
def test_classic_data_extract() -> None:
    """Test CLASSIC_Main's `classic_data_extract()`."""
    zip_path = Path("CLASSIC Data.zip")
    data_path = Path("CLASSIC Data")
    yaml_path = Path("CLASSIC Data/databases/CLASSIC Main.yaml")

    assert not data_path.exists(), "CLASSIC Data folder existed before testing"

    pytest.raises(FileNotFoundError, CLASSIC_Main.classic_data_extract)

    with zip_path.open("wb") as f:
        f.write(binascii.unhexlify(TEST_ZIP))

    return_value = CLASSIC_Main.classic_data_extract()  # type: ignore[func-returns-value]
    assert return_value is None, "classic_data_extract() unexpectedly returned a value"

    assert data_path.is_dir(), f"{data_path} was not created"
    assert yaml_path.is_file(), f"{yaml_path} was not extracted"

    zip_path.unlink(missing_ok=True)
    assert not zip_path.exists(), f"Failed to delete {zip_path}"


def test_open_file_with_encoding() -> None:
    """Test CLASSIC_Main's `open_file_with_encoding()`."""
    utf16_path = Path("tests/utf16le.txt")
    utf16_path.unlink(missing_ok=True)

    with utf16_path.open("wb") as f:
        f.write(binascii.unhexlify(TEST_UTF16LE))

    with CLASSIC_Main.open_file_with_encoding(str(utf16_path)) as f:
        pass

    with CLASSIC_Main.open_file_with_encoding(utf16_path) as f:
        encoding = f.encoding

    assert encoding == "UTF-16", "Failed to detect file encoding"

    utf16_path.unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_gamevars")
async def test_classic_update_check(yaml_cache: CLASSIC_Main.YamlSettingsCache) -> None:
    """Test CLASSIC_Main's `classic_update_check()`."""
    # Fake the YAML cache to prevent loading real values.
    yaml_path = Path("CLASSIC Data/databases/CLASSIC Main.yaml")
    if yaml_path.exists():
        last_mod_time = yaml_path.stat().st_mtime
        yaml_cache.file_mod_times[yaml_path] = last_mod_time

    game = CLASSIC_Main.gamevars["game"]

    yaml_cache.cache[yaml_path] = ruamel.yaml.CommentedMap({
        "CLASSIC_Info": {"version": LATEST_VERSION},
        "CLASSIC_Interface": {f"update_warning_{game}": "", f"update_unable_{game}": ""},
    })

    return_value = await CLASSIC_Main.classic_update_check(quiet=False, gui_request=True)
    assert return_value is True, "classic_update_check() should return True"

    yaml_cache.cache[yaml_path]["CLASSIC_Info"]["version"] = "CLASSIC v7.25.1"

    return_value = await CLASSIC_Main.classic_update_check(quiet=False, gui_request=True)
    assert return_value is False, "classic_update_check() should return False"


@pytest.mark.usefixtures("_move_user_files", "_gamevars")
def test_docs_path_find(yaml_cache: CLASSIC_Main.YamlSettingsCache) -> None:
    """Test CLASSIC_Main's `docs_path_find()`."""
    if CLASSIC_Main.manual_docs_gui is None:
        manual_docs_gui_backup = None
    else:
        manual_docs_gui_backup = CLASSIC_Main.manual_docs_gui
        CLASSIC_Main.manual_docs_gui = None

    pytest.raises(TypeError, CLASSIC_Main.docs_path_find)

    if manual_docs_gui_backup is None:
        CLASSIC_Main.manual_docs_gui = CLASSIC_Main.ManualDocsPath()
    else:
        CLASSIC_Main.manual_docs_gui = manual_docs_gui_backup

    game = CLASSIC_Main.gamevars["game"]

    # Fake the YAML cache to prevent loading real values.
    yaml_path = Path(f"CLASSIC Data/databases/CLASSIC {game}.yaml")
    if yaml_path.exists():
        last_mod_time = yaml_path.stat().st_mtime
        yaml_cache.file_mod_times[yaml_path] = last_mod_time

    yaml_cache.cache[yaml_path] = ruamel.yaml.CommentedMap({
        "Game_Info": {"Main_Docs_Name": game},
    })

    yaml_local_path = Path(f"CLASSIC Data/CLASSIC {game} Local.yaml")
    assert not yaml_local_path.exists(), f"{yaml_local_path} existed before testing"

    CLASSIC_Main.docs_path_find()

    assert yaml_local_path.is_file(), f"{yaml_local_path} was not created"
    assert yaml_local_path.stat().st_size > 0, f"{yaml_local_path} was not written to"
    yaml_local_path.unlink(missing_ok=True)
    assert not yaml_local_path.exists(), f"{yaml_local_path} was not deleted"


@pytest.mark.usefixtures("_move_user_files", "_gamevars")
def test_game_path_find(yaml_cache: CLASSIC_Main.YamlSettingsCache) -> None:
    """Test CLASSIC_Main's `game_path_find()`."""
    if CLASSIC_Main.game_path_gui is None:
        game_path_gui_backup = None
    else:
        game_path_gui_backup = CLASSIC_Main.game_path_gui
        CLASSIC_Main.game_path_gui = None

    pytest.raises(TypeError, CLASSIC_Main.game_path_find)

    if game_path_gui_backup is None:
        CLASSIC_Main.game_path_gui = CLASSIC_Main.GamePathEntry()
    else:
        CLASSIC_Main.game_path_gui = game_path_gui_backup

    game = CLASSIC_Main.gamevars["game"] = "Fallout4"
    XSE_Acronym = "F4SE"
    Main_Root_Name = "Fallout 4"
    xse_log_path = Path(f"tests/{XSE_Acronym.lower()}.log")

    # Fake the YAML cache to prevent loading real values.
    yaml_local_path = Path(f"CLASSIC Data/CLASSIC {game} Local.yaml")
    yaml_path = Path(f"CLASSIC Data/databases/CLASSIC {game}.yaml")
    if yaml_path.exists():
        last_mod_time = yaml_path.stat().st_mtime
        yaml_cache.file_mod_times[yaml_path] = last_mod_time

    yaml_cache.cache[yaml_local_path] = ruamel.yaml.CommentedMap({"Game_Info": {"Docs_File_XSE": "FAKE_PATH"}})
    yaml_cache.cache[yaml_path] = ruamel.yaml.CommentedMap({
        "Game_Info": {"Main_Docs_Name": game, "XSE_Acronym": XSE_Acronym, "Main_Root_Name": Main_Root_Name},
    })

    assert not yaml_local_path.exists(), f"{yaml_local_path} existed before testing"

    # Test with no XSE log
    CLASSIC_Main.game_path_find()
    assert not yaml_local_path.is_file(), f"{yaml_local_path} was unxepectedly created"

    yaml_cache.cache[yaml_local_path]["Game_Info"]["Docs_File_XSE"] = str(xse_log_path)

    xse_log_path.unlink(missing_ok=True)
    with xse_log_path.open("w") as f:
        f.write(TEST_F4SE_LOG)

    CLASSIC_Main.game_path_find()
    xse_log_path.unlink(missing_ok=True)

    assert yaml_local_path.is_file(), f"{yaml_local_path} was not created"
    assert yaml_local_path.stat().st_size > 0, f"{yaml_local_path} was not written to"
    yaml_local_path.unlink(missing_ok=True)
    assert not yaml_local_path.exists(), f"{yaml_local_path} was not deleted"
