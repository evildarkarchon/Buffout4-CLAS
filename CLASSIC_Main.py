import configparser
import contextlib
import datetime
import hashlib
import logging
import os
import platform
import shutil
import stat
import sys
import zipfile
from collections.abc import Iterator
from enum import Enum, auto
from functools import reduce
from io import TextIOWrapper
from pathlib import Path
from typing import Literal, TypedDict

import aiohttp
import chardet
import ruamel.yaml
from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, Signal

with contextlib.suppress(ImportError):
    import winreg

""" AUTHOR NOTES (POET): ❓ ❌ ✔️
    ❓ REMINDER: 'shadows x from outer scope' means the variable name repeats both in the func and outside all other func.
    ❓ Comments marked as RESERVED in all scripts are intended for future updates or tests, do not edit / move / remove.
    ❓ (..., encoding="utf-8", errors="ignore") needs to go with every opened file because of unicode & charmap errors.
    ❓ import shelve if you want to store persistent data that you do not want regular users to access or modify.
    ❓ Globals are generally used to standardize game paths and INI files naming conventions.
"""

type YAMLLiteral = str | int | bool
type YAMLSequence = list[str]
type YAMLMapping = dict[str, "YAMLValue"]
type YAMLValue = YAMLMapping | YAMLSequence | YAMLLiteral
type YAMLValueOptional = YAMLValue | None
type GameID = Literal["Fallout4", "Fallout4VR", "Skyrim", "Starfield"] # Entries must correspond to the game's Main ESM or EXE file name.

class YAML(Enum):
    Main = auto()
    """CLASSIC Data/databases/CLASSIC Main.yaml"""
    Settings = auto()
    """CLASSIC Settings.yaml"""
    Ignore = auto()
    """CLASSIC Ignore.yaml"""
    Game = auto()
    """CLASSIC Data/databases/CLASSIC Fallout4.yaml"""
    Game_Local = auto()
    """CLASSIC Data/CLASSIC Fallout4 Local.yaml"""
    TEST = auto()
    """tests/test_settings.yaml"""

class GameVars(TypedDict):
    game: GameID
    vr: Literal["VR", ""]

gamevars: GameVars = {
    "game": "Fallout4",
    "vr": "",
}

NULL_VERSION = Version("0.0.0")

class UpdateCheckError(Exception):
    """Checking for updates failed."""

SETTINGS_IGNORE_NONE = {
    "SCAN Custom Path",
    "MODS Folder Path",
    "Root_Folder_Game",
    "Root_Folder_Docs",
}

logger = logging.getLogger()


class ManualDocsPath(QObject):
    manual_docs_path_signal = Signal()

    def __init__(self) -> None:
        super().__init__()

    def get_manual_docs_path_gui(self, path: str) -> None:
        if Path(path).is_dir():
            print(f"You entered: '{path}' | This path will be automatically added to CLASSIC Settings.yaml")
            manual_docs = Path(path.strip())
            yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(manual_docs))
        else:
            print(f"'{path}' is not a valid or existing directory path. Please try again.")
            self.manual_docs_path_signal.emit()


class GamePathEntry(QObject):
    game_path_signal = Signal()

    def __init__(self) -> None:
        super().__init__()

    def get_game_path_gui(self, path: str) -> None:
        if Path(path).is_dir():
            print(f"You entered: '{path}' | This path will be automatically added to CLASSIC Settings.yaml")
            game_path = Path(path.strip())
            yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game", str(game_path))
        else:
            print(f"'{path}' is not a valid or existing directory path. Please try again.")
            self.game_path_signal.emit()


@contextlib.contextmanager
def open_file_with_encoding(file_path: Path | str | os.PathLike) -> Iterator[TextIOWrapper]:
    """Read only file open with encoding detection. Only for text files."""
    if not isinstance(file_path, Path):
        file_path = Path(file_path)
    raw_data = file_path.read_bytes()
    encoding = chardet.detect(raw_data)["encoding"]

    file_handle = file_path.open(encoding=encoding, errors="ignore")
    try:
        yield file_handle
    finally:
        file_handle.close()


def configure_logging() -> None:
    """Configure log output to `CLASSIC Journal.log`, regenerating if older than 7 days.

    Logging levels: debug | info | warning | error | critical.
    """
    global logger  # noqa: PLW0603

    journal_path = Path("CLASSIC Journal.log")
    if journal_path.exists():
        logger.debug("- - - INITIATED LOGGING CHECK")
        log_time = datetime.datetime.fromtimestamp(journal_path.stat().st_mtime)
        current_time = datetime.datetime.now()
        log_age = current_time - log_time
        if log_age.days > 7:
            try:
                journal_path.unlink(missing_ok=True)
                print("CLASSIC Journal.log has been deleted and regenerated due to being older than 7 days.")
            except (ValueError, OSError) as err:
                print(f"An error occurred while deleting {journal_path.name}: {err}")

    # Make sure we only configure the handler once
    if "CLASSIC" not in logging.Logger.manager.loggerDict:
        logger = logging.getLogger("CLASSIC")
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(
            filename="CLASSIC Journal.log",
            mode="a",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)


# ================================================
# DEFINE FILE / YAML FUNCTIONS
# ================================================
def remove_readonly(file_path: Path) -> None:
    """Remove the read-only flag from a given file, if present."""
    try:
        if platform.system() == "Windows":
            if file_path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY == 1:
                file_path.chmod(stat.S_IWRITE)
                logger.debug(f"- - - '{file_path}' is no longer Read-Only.")
            else:
                logger.debug(f"- - - '{file_path}' is not set to Read-Only.")
        else:
            # Get current file permissions.
            permissions = file_path.stat().st_mode & 0o777
            if permissions & (os.O_RDONLY | os.O_WRONLY):
                # Remove file permissions if needed.
                file_path.chmod(permissions | 0o200)
                logger.debug(f"- - - '{file_path}' is no longer Read-Only.")
            else:
                logger.debug(f"- - - '{file_path}' is not set to Read-Only.")

    except FileNotFoundError:
        logger.error(f"> > > ERROR (remove_readonly) : '{file_path}' not found.")
    except (ValueError, OSError) as err:
        logger.error(f"> > > ERROR (remove_readonly) : {err}")


class YamlSettingsCache:
    def __init__(self) -> None:
        self.cache: dict[Path, YAMLMapping] = {}
        self.file_mod_times: dict[Path, float] = {}

    def load_yaml(self, yaml_path: str | os.PathLike) -> YAMLMapping:
        # Use pathlib for file handling and caching
        yaml_path = Path(yaml_path)
        if yaml_path.exists():
            # Check if the file has been modified since it was last cached
            last_mod_time = yaml_path.stat().st_mtime
            if (yaml_path not in self.file_mod_times or
                self.file_mod_times[yaml_path] != last_mod_time):

                # Update the file modification time
                self.file_mod_times[yaml_path] = last_mod_time

                # Reload the YAML file
                with yaml_path.open(encoding="utf-8") as yaml_file:
                    yaml = ruamel.yaml.YAML()
                    yaml.indent(offset=2)
                    yaml.width = 300
                    self.cache[yaml_path] = yaml.load(yaml_file)

        return self.cache.get(yaml_path, {})

    def get_setting[T](self, _type: type[T], yaml_store: YAML, key_path: str, new_value: T | None = None) -> T | None:
        data_path = Path("CLASSIC Data/")
        match yaml_store:
            case YAML.Main:
                yaml_path = data_path / "databases/CLASSIC Main.yaml"
            case YAML.Settings:
                yaml_path = Path("CLASSIC Settings.yaml")
            case YAML.Ignore:
                yaml_path = Path("CLASSIC Ignore.yaml")
            case YAML.Game:
                yaml_path = data_path / f"databases/CLASSIC {gamevars["game"]}.yaml"
            case YAML.Game_Local:
                yaml_path = data_path / f"CLASSIC {gamevars["game"]} Local.yaml"
            case YAML.TEST:
                yaml_path = Path("tests/test_settings.yaml")
            case _:
                raise NotImplementedError

        #assert yaml_path.is_file()
        data = self.load_yaml(yaml_path)
        keys = key_path.split(".")

        def setdefault(dictionary: dict[str, YAMLValue], key: str) -> dict[str, YAMLValue]:
            if key not in dictionary:
                dictionary[key] = {}
            next_value = dictionary[key]
            if not isinstance(next_value, dict):
                raise TypeError
            return next_value

        setting_container = reduce(setdefault, keys[:-1], data)

        # If new_value is provided, update the value
        if new_value is not None:
            setting_container[keys[-1]] = new_value  # type: ignore[assignment]

            # Write changes back to the YAML file
            with yaml_path.open("w", encoding="utf-8") as yaml_file:
                yaml = ruamel.yaml.YAML()
                yaml.indent(offset=2)
                yaml.width = 300
                yaml.dump(data, yaml_file)

            # Update the cache
            self.cache[yaml_path] = data
            return new_value

        # Traverse YAML structure to get value
        setting_value = setting_container.get(keys[-1])
        if setting_value is None and keys[-1] not in SETTINGS_IGNORE_NONE:
            print(f"❌ ERROR (yaml_settings) : Trying to grab a None value for : '{key_path}'")
        return setting_value  # type: ignore[return-value]


def yaml_settings[T](_type: type[T], yaml_store: YAML, key_path: str, new_value: T | None = None) -> T | None:
    if yaml_cache is None:
        raise TypeError("CMain not initialized")
    setting = yaml_cache.get_setting(_type, yaml_store, key_path, new_value)
    if _type is Path:
        return Path(setting) if setting and isinstance(setting, str) else None  # type: ignore[return-value]
    return setting


def classic_settings[T](_type: type[T], setting: str) -> T | None:
    settings_path = Path("CLASSIC Settings.yaml")
    if not settings_path.exists():
        default_settings = yaml_settings(str, YAML.Main, "CLASSIC_Info.default_settings")
        if not isinstance(default_settings, str):
            raise ValueError("Invalid Default Settings in 'CLASSIC Main.yaml'")

        settings_path.write_text(default_settings, encoding="utf-8")

    return yaml_settings(_type, YAML.Settings, f"CLASSIC_Settings.{setting}")


# ================================================
# CREATE REQUIRED FILES, SETTINGS & UPDATE CHECK
# ================================================
def classic_generate_files() -> None:
    """Generate `CLASSIC Ignore.yaml` and `CLASSIC Data/CLASSIC <GAME> Local.yaml`."""
    ignore_path = Path("CLASSIC Ignore.yaml")
    if not ignore_path.exists():
        default_ignorefile = yaml_settings(str, YAML.Main, "CLASSIC_Info.default_ignorefile")
        if not isinstance(default_ignorefile, str):
            raise TypeError
        ignore_path.write_text(default_ignorefile, encoding="utf-8")

    local_path = Path(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml")
    if not local_path.exists():
        default_yaml = yaml_settings(str, YAML.Main, "CLASSIC_Info.default_localyaml")
        if not isinstance(default_yaml, str):
            raise TypeError
        local_path.write_text(default_yaml, encoding="utf-8")


def classic_data_extract() -> None:
    """Extract `CLASSIC Data.zip` if `CLASSIC Main.yaml` is not found."""
    def open_zip() -> zipfile.ZipFile:
        exe = sys.executable if getattr(sys, "frozen", False) else __file__
        exedir = Path(exe).parent

        if datafile := next(exedir.rglob("CLASSIC Data.zip", case_sensitive=False), None):
            return zipfile.ZipFile(datafile)
        raise FileNotFoundError
    try:
        if not Path("CLASSIC Data/databases/CLASSIC Main.yaml").exists():
            with open_zip() as zip_data:
                zip_data.extractall("CLASSIC Data")
    except FileNotFoundError:
        print("❌ ERROR : UNABLE TO FIND CLASSIC Data.zip! This archive is required for CLASSIC to function.")
        print("Please ensure that you have extracted all CLASSIC files into the same folder after downloading.")
        raise


def try_parse_version(version_string: str) -> Version | None:
    try:
        return Version(version_string)
    except InvalidVersion:
        return None


async def get_github_version(session: aiohttp.ClientSession) -> Version | None:
    """Check the latest CLASSIC version on GitHub.

    Returns a Version for the latest release if successful.
    Returns None if the check fails.
    """
    try:
        async with session.get("https://api.github.com/repos/evildarkarchon/CLASSIC-Fallout4/releases/latest") as response:
            response_json = await response.json()
    except aiohttp.ClientError:
        return None

    # The JSON should have this field with the title of the latest release:
    # "name": "CLASSIC v7.30.3"
    if isinstance(response_json, dict):
        release_name = response_json.get("name")
        if release_name and isinstance(release_name, str):
            return try_parse_version(release_name.rsplit(maxsplit=1)[-1])
    return None


async def get_nexus_version(session: aiohttp.ClientSession) -> Version | None:
    """Check the latest CLASSIC version on Nexus Mods.

    Returns the Version on the mod page if successful.
    Returns None if the check fails.
    """
    try:
        async with session.get("https://www.nexusmods.com/fallout4/mods/56255") as response:
            use_next = False
            async for line in response.content:
                # We're looking for these lines:
                #    <meta property="twitter:label1" content="Version" />
                #    <meta property="twitter:data1" content="7.30.3" />
                # We'll find the label and then use the next line.
                # If we hit the stylesheet tags we've gone too far.
                # The HTML likely changed and this needs updating.
                line_text = line.decode("utf-8")
                if line_text.startswith('<meta property="twitter:label1" content="Version"'):
                    use_next = True
                    continue
                if use_next:
                    # [ '<meta property="twitter:data1" content=',
                    #   '7.30.3',
                    #   ' />' ]
                    split = line_text.rsplit('"', 2)
                    if len(split) == 3:
                        return try_parse_version(split[1])
                    break
                if line_text.startswith('<link rel="stylesheet"'):
                    break
    except aiohttp.ClientError:
        pass
    return None


# New name transition aid. TODO: Remove when no longer needed.
async def classic_update_check(quiet: bool = False, gui_request: bool = True) -> bool:
    return await is_latest_version(quiet, gui_request)


async def is_latest_version(quiet: bool = False, gui_request: bool = True) -> bool:
    """Check GitHub and Nexus Mods for newer versions, depending on settings.

    Returns True if CLASSIC is already the latest version, False otherwise.
    """
    logger.debug("- - - INITIATED UPDATE CHECK")
    if not (gui_request or classic_settings(bool, "Update Check")):
        if not quiet:
            print(
                "\n❌ NOTICE: UPDATE CHECK IS DISABLED IN CLASSIC Settings.yaml \n",
                "\n===============================================================================",
                flush=True
            )
        return False

    update_source = classic_settings(str, "Update Source") or "Both"
    if update_source not in {"Both", "GitHub", "Nexus"}:
        if not quiet:
            print(
                "\n❌ NOTICE: INVALID VALUE FOR UPDATE SOURCE IN CLASSIC Settings.yaml \n",
                "\n===============================================================================",
                flush=True,
            )
        return False

    classic_local = yaml_settings(str, YAML.Main, "CLASSIC_Info.version")
    if not quiet:
        print(
            "❓ (Needs internet connection) CHECKING FOR NEW CLASSIC VERSIONS...",
            "\n   (You can disable this check in the EXE or CLASSIC Settings.yaml) \n",
            flush=True
        )

    use_github = update_source in {"Both", "GitHub"}
    use_nexus = update_source in {"Both", "Nexus"}
    no_data: set[None | Version] = {None, NULL_VERSION}
    try:
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            version_github = await get_github_version(session) if use_github else NULL_VERSION
            version_nexus = await get_nexus_version(session) if use_nexus else NULL_VERSION
        if version_github in no_data and version_nexus in no_data:
            # Unable to check any chosen sources
            raise UpdateCheckError  # noqa: TRY301

    except (ValueError, OSError, aiohttp.ClientError, UpdateCheckError) as err:
        if not quiet:
            print(err, flush=True)
            print(yaml_settings(str, YAML.Main, f"CLASSIC_Interface.update_unable_{gamevars["game"]}"), flush=True)
        if gui_request:
            # GUI catches exceptions to detect update failures.
            raise UpdateCheckError from err
        return False

    # Split "CLASSIC" from the version for YAML and GitHub; "CLASSIC v7.30.3"
    version_local = try_parse_version(classic_local.rsplit(maxsplit=1)[-1]) if classic_local else NULL_VERSION

    if (
        version_local is None  # Local version unknown; updating may fix
        or (version_github is not None and version_local < version_github)
        or (version_nexus is not None and version_local < version_nexus)
    ):
        if not quiet:
            print(yaml_settings(str, YAML.Main, f"CLASSIC_Interface.update_warning_{gamevars["game"]}"), flush=True)
        if gui_request:
            raise UpdateCheckError
        return False

    if not quiet:
        print(
            f"Your CLASSIC Version: {version_local}",
            f"\nLatest GitHub Version: {version_github}" if use_github else "",
            f"\nLatest Nexus Version: {version_nexus}" if use_nexus else "",
            "\n\n✔️ You have the latest version of CLASSIC!\n",
            sep="",
            flush=True,
        )
    return True


# ================================================
# CHECK DEFAULT DOCUMENTS & GAME FOLDERS / FILES
# ================================================
# =========== CHECK DOCUMENTS FOLDER PATH -> GET GAME DOCUMENTS FOLDER ===========
def docs_path_find() -> None:
    logger.debug("- - - INITIATED DOCS PATH CHECK")

    # Retrieve the document name from YAML settings
    docs_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_Docs_Name")
    if not isinstance(docs_name, str):
        docs_name = gamevars["game"]

    def get_windows_docs_path() -> None:
        try:
            # Open the registry key to get the user's documents path
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders") as key:  # pyright: ignore[reportPossiblyUnboundVariable]
                documents_path = Path(winreg.QueryValueEx(key, "Personal")[0]) # pyright: ignore[reportPossiblyUnboundVariable]
        except (OSError, UnboundLocalError):
            # Fallback to a default path if registry key is not found
            documents_path = Path.home() / "Documents"

        # Construct the full path to the game's documents folder
        win_docs = str(documents_path / "My Games" / docs_name)

        # Update the YAML settings with the documents path
        yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", win_docs)

    def get_linux_docs_path() -> None:
        # Retrieve the Steam ID from YAML settings
        game_sid = yaml_settings(int, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_SteamID")
        if not isinstance(game_sid, int):
            raise TypeError

        # Path to the Steam library folders configuration file
        libraryfolders_path = Path.home() / ".local/share/Steam/steamapps/common/libraryfolders.vdf"

        if libraryfolders_path.is_file():
            library_path = Path()
            with libraryfolders_path.open(encoding="utf-8", errors="ignore") as steam_library_raw:
                steam_library = steam_library_raw.readlines()

            for library_line in steam_library:
                if "path" in library_line:
                    library_path = Path(library_line.split('"')[3])
                if str(game_sid) in library_line:
                    library_path = library_path / "steamapps"
                    linux_docs = library_path / "compatdata" / str(game_sid) / "pfx/drive_c/users/steamuser/My Documents/My Games" / docs_name
                    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(linux_docs))

    def get_manual_docs_path() -> None:
        print(f"> > > PLEASE ENTER THE FULL DIRECTORY PATH WHERE YOUR {docs_name}.ini IS LOCATED < < <")
        while True:
            input_str = input(f"(EXAMPLE: C:/Users/Zen/Documents/My Games/{docs_name} | Press ENTER to confirm.)\n> ").strip()
            input_path = Path(input_str)
            if input_str and input_path.is_dir():
                print(f"You entered: '{input_str}' | This path will be automatically added to CLASSIC Settings.yaml")
                yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(input_path))
                break

            print(f"'{input_str}' is not a valid or existing directory path. Please try again.")

    # =========== CHECK IF GAME DOCUMENTS FOLDER PATH WAS GENERATED AND FOUND ===========
    docs_path = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")
    if not isinstance(docs_path, str):
        docs_path = None

    if docs_path is None:
        if platform.system() == "Windows":
            get_windows_docs_path()
        else:
            get_linux_docs_path()

    docs_path = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")
    if not isinstance(docs_path, str):
        docs_path = None

    if docs_path and not Path(docs_path).is_dir():
        if gui_mode:
            if manual_docs_gui is None:
                raise TypeError("CMain not initialized")
            manual_docs_gui.manual_docs_path_signal.emit()
        else:
            get_manual_docs_path()

def get_manual_docs_path_gui(path: str) -> None:
    if manual_docs_gui is None:
        raise TypeError("CMain not initialized")

    path = path.strip()
    if Path(path).is_dir():
        file_found: bool = False
        for file in Path(path).rglob("*.ini"):
            if f"{gamevars["game"]}.ini" in file.name:
                print(f"You entered: '{path}' | This path will be automatically added to CLASSIC Settings.yaml")
                manual_docs = Path(path)
                yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(manual_docs))
                file_found = True
                break
        if not file_found:
            print(f"❌ ERROR : NO {gamevars["game"]}.ini FILE FOUND IN '{path}'! Please try again.")
            manual_docs_gui.manual_docs_path_signal.emit()
    else:
        print(f"'{path}' is not a valid or existing directory path. Please try again.")
        manual_docs_gui.manual_docs_path_signal.emit()

def docs_generate_paths() -> None:
    logger.debug("- - - INITIATED DOCS PATH GENERATION")
    xse_acronym = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Acronym")
    xse_acronym_base = yaml_settings(str, YAML.Game, "Game_Info.XSE_Acronym")
    docs_path_str = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")
    if not (isinstance(xse_acronym, str) and isinstance(xse_acronym_base, str) and isinstance(docs_path_str, str)):
        raise TypeError
    docs_path = Path(docs_path_str)

    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_Folder_XSE", str(docs_path.joinpath(xse_acronym_base)))
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_PapyrusLog", str(docs_path.joinpath("Logs/Script/Papyrus.0.log")))
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_WryeBashPC", str(docs_path.joinpath("ModChecker.html")))
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_XSE", str(docs_path.joinpath(xse_acronym_base, f"{xse_acronym.lower()}.log")))


# =========== CHECK DOCUMENTS XSE FILE -> GET GAME ROOT FOLDER PATH ===========
def game_path_find() -> None:
    logger.debug("- - - INITIATED GAME PATH CHECK")

    try:
        # Open the registry key
        reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Bethesda Softworks\{gamevars["game"]}{gamevars["vr"]}")  # pyright: ignore[reportPossiblyUnboundVariable]
        # Query the 'installed path' value
        path, _ = winreg.QueryValueEx(reg_key, "installed path")  # pyright: ignore[reportPossiblyUnboundVariable]
        winreg.CloseKey(reg_key)  # pyright: ignore[reportPossiblyUnboundVariable]
    except (UnboundLocalError, OSError):
        game_path = None
    else:
        game_path = Path(path) if path else None

    exe_name = f"{gamevars["game"]}{gamevars["vr"]}.exe"

    if game_path and game_path.is_dir() and game_path.joinpath(exe_name).is_file():
        yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game", str(game_path))
        return

    xse_file = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_XSE")
    xse_acronym = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Acronym")
    xse_acronym_base = yaml_settings(str, YAML.Game, "Game_Info.XSE_Acronym")
    game_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_Root_Name")
    if not (isinstance(xse_file, str) or xse_file is None):
        raise TypeError
    if not (isinstance(xse_acronym, str) and isinstance(xse_acronym_base, str) and isinstance(game_name, str)):
        raise TypeError

    if not xse_file or not Path(xse_file).is_file():
        print(f"❌ CAUTION : THE {xse_acronym.lower()}.log FILE IS MISSING FROM YOUR GAME DOCUMENTS FOLDER! \n")
        print(f"   You need to run the game at least once with {xse_acronym.lower()}_loader.exe \n")
        print("    After that, try running CLASSIC again! \n-----\n")
        return

    with open_file_with_encoding(xse_file) as LOG_Check:
        Path_Check = LOG_Check.readlines()
    for logline in Path_Check:
        if logline.startswith("plugin directory"):
            logline = logline.split("=", maxsplit=1)[1].strip().replace(f"\\Data\\{xse_acronym_base}\\Plugins", "").replace("\n", "")
            game_path = Path(logline)
            break
    if game_path and game_path.is_dir() and game_path.joinpath(exe_name).is_file():
        yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game", str(game_path))
        return

    if gui_mode:
        if game_path_gui is None:
            raise TypeError("CMain not initialized")
        game_path_gui.game_path_signal.emit()
        return

    while True:
        print(f"> > PLEASE ENTER THE FULL DIRECTORY PATH WHERE YOUR {game_name} IS LOCATED < <")
        path_input = input(fr"(EXAMPLE: C:\Steam\steamapps\common\{game_name} | Press ENTER to confirm.)\n> ")
        print(f"You entered: {path_input} | This path will be automatically added to CLASSIC Settings.yaml")
        game_path = Path(path_input.strip())
        if game_path and game_path.joinpath(exe_name).is_file():
            yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game", str(game_path))
            return
        print(f"❌ ERROR : NO {gamevars["game"]}{gamevars["vr"]}.exe FILE FOUND IN '{game_path}'! Please try again.")


def game_generate_paths() -> None:
    logger.debug("- - - INITIATED GAME PATH GENERATION")

    game_path = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game")
    yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Acronym")
    xse_acronym_base = yaml_settings(str, YAML.Game, "Game_Info.XSE_Acronym")
    if not (isinstance(game_path, str) and isinstance(xse_acronym_base, str)):
        raise TypeError

    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_Folder_Data", rf"{game_path}\Data")
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_Folder_Scripts", rf"{game_path}\Data\Scripts")
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_Folder_Plugins", fr"{game_path}\Data\{xse_acronym_base}\Plugins")
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_File_SteamINI", rf"{game_path}\steam_api.ini")
    yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_File_EXE", fr"{game_path}\{gamevars["game"]}{gamevars["vr"]}.exe")
    match gamevars["game"]:
        case "Fallout4" if not gamevars["vr"]:
            yaml_settings(str, YAML.Game_Local, "Game_Info.Game_File_AddressLib", fr"{game_path}\Data\{xse_acronym_base}\plugins\version-1-10-163-0.bin")
        case "Fallout4" if gamevars["vr"]:
            yaml_settings(str, YAML.Game_Local, "GameVR_Info.Game_File_AddressLib", fr"{game_path}\Data\{xse_acronym_base}\plugins\version-1-2-72-0.csv")


# =========== CHECK GAME EXE FILE -> GET PATH AND HASHES ===========
def game_check_integrity() -> str:
    message_list = []
    logger.debug("- - - INITIATED GAME INTEGRITY CHECK")

    steam_ini_local = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_File_SteamINI")
    exe_hash_old = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.EXE_HashedOLD")
    # exe_hash_new = yaml_settings(YAML.Game, f"Game{gamevars["vr"]}_Info.EXE_HashedNEW")  # RESERVED FOR 2023 UPDATE
    game_exe_local = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_File_EXE")
    root_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_Root_Name")
    if not (isinstance(exe_hash_old, str) and isinstance(root_name, str)):
        raise TypeError
    if not (isinstance(steam_ini_local, str) or steam_ini_local is None):
        raise TypeError
    if not (isinstance(game_exe_local, str) or game_exe_local is None):
        raise TypeError

    game_exe_path = Path(game_exe_local) if game_exe_local else None
    steam_ini_path = Path(steam_ini_local) if steam_ini_local else None
    if game_exe_path and game_exe_path.is_file():
        with game_exe_path.open("rb") as f:
            file_contents = f.read()
            # Algo should match the one used for Database YAML!
            exe_hash_local = hashlib.sha256(file_contents).hexdigest()
        # print(f"LOCAL: {exe_hash_local}\nDATABASE: {exe_hash_old}")
        if exe_hash_local == exe_hash_old and not (steam_ini_path and steam_ini_path.exists()):
            message_list.append(f"✔️ You have the latest version of {root_name}! \n-----\n")
        elif steam_ini_path and steam_ini_path.exists():
            message_list.append(f"\U0001F480 CAUTION : YOUR {root_name} GAME / EXE VERSION IS OUT OF DATE \n-----\n")
        else:
            message_list.append(f"❌ CAUTION : YOUR {root_name} GAME / EXE VERSION IS OUT OF DATE \n-----\n")

        if "Program Files" not in str(game_exe_path):
            message_list.append(f"✔️ Your {root_name} game files are installed outside of the Program Files folder! \n-----\n")
        else:
            root_warn = yaml_settings(str, YAML.Main, "Warnings_GAME.warn_root_path")
            if not isinstance(root_warn, str):
                raise TypeError
            message_list.append(root_warn)

    return "".join(message_list)


# =========== CHECK GAME XSE SCRIPTS -> GET PATH AND HASHES ===========
def xse_check_integrity() -> str:  # RESERVED | NEED VR HASH/FILE CHECK
    failed_list: list[str] = []
    message_list: list[str] = []
    logger.debug("- - - INITIATED XSE INTEGRITY CHECK")

    catch_errors = yaml_settings(list[str], YAML.Main, "catch_log_errors")
    xse_acronym = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Acronym")
    xse_log_file = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_XSE")
    xse_full_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_FullName")
    xse_ver_latest = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Ver_Latest")
    adlib_file_str = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_File_AddressLib")
    if not isinstance(catch_errors, list):
        raise TypeError
    if not (isinstance(xse_acronym, str) and isinstance(xse_full_name, str) and isinstance(xse_ver_latest, str)):
        raise TypeError
    if not (isinstance(xse_log_file, str) or xse_log_file is None):
        raise TypeError
    if not (isinstance(adlib_file_str, str) or adlib_file_str is None):
        raise TypeError
    adlib_file = Path(adlib_file_str) if adlib_file_str else None

    match adlib_file:
        case str() | Path():
            if Path(adlib_file).exists():
                message_list.append("✔️ REQUIRED: *Address Library* for Script Extender is installed! \n-----\n")
            else:
                warn_adlib = yaml_settings(str, YAML.Game, "Warnings_MODS.Warn_ADLIB_Missing")
                if not isinstance(warn_adlib, str):
                    raise TypeError
                message_list.append(warn_adlib)
        case _:
            message_list.append(f"❌ Value for Address Library is invalid or missing from CLASSIC {gamevars["game"]} Local.yaml!\n-----\n")

    match xse_log_file:
        case str() | Path():
            if Path(xse_log_file).exists():
                message_list.append(f"✔️ REQUIRED: *{xse_full_name}* is installed! \n-----\n")
                with open_file_with_encoding(xse_log_file) as xse_log:
                    xse_data = xse_log.readlines()
                if str(xse_ver_latest) in xse_data[0]:
                    message_list.append(f"✔️ You have the latest version of *{xse_full_name}*! \n-----\n")
                else:
                    warn_outdated = yaml_settings(str, YAML.Game, "Warnings_XSE.Warn_Outdated")
                    if not isinstance(warn_outdated, str):
                        raise TypeError
                    message_list.append(warn_outdated)
                failed_list.extend([
                    line for line in xse_data if any(item.lower() in line.lower() for item in catch_errors)
                ])

                if failed_list:
                    message_list.append(f"#❌ CAUTION : {xse_acronym}.log REPORTS THE FOLLOWING ERRORS #\n")
                    message_list.extend([f"ERROR > {elem.strip()} \n-----\n" for elem in failed_list])
            else:
                message_list.extend([f"❌ CAUTION : *{xse_acronym.lower()}.log* FILE IS MISSING FROM YOUR DOCUMENTS FOLDER! \n",
                                    f"   You need to run the game at least once with {xse_acronym.lower()}_loader.exe \n",
                                    "    After that, try running CLASSIC again! \n-----\n"])
        case _:
            message_list.append(f"❌ Value for {xse_acronym.lower()}.log is invalid or missing from CLASSIC {gamevars["game"]} Local.yaml!\n-----\n")

    return "".join(message_list)


def xse_check_hashes() -> str:
    message_list: list[str] = []
    logger.debug("- - - INITIATED XSE FILE HASH CHECK")

    xse_script_missing = xse_script_mismatch = False
    xse_hashedscripts = yaml_settings(dict[str, str], YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_HashedScripts")
    game_folder_scripts = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Game_Folder_Scripts")
    if not isinstance(xse_hashedscripts, dict):
        raise TypeError
    if not (isinstance(game_folder_scripts, str) or game_folder_scripts is None):
        raise TypeError

    xse_hashedscripts_local = dict.fromkeys(xse_hashedscripts)
    for key in xse_hashedscripts_local:
        script_path = Path(rf"{game_folder_scripts}\{key!s}")
        if script_path.is_file():
            with script_path.open("rb") as f:
                file_contents = f.read()
                # Algo should match the one used for Database YAML!
                file_hash = hashlib.sha256(file_contents).hexdigest()
                xse_hashedscripts_local[key] = str(file_hash)

    for key in xse_hashedscripts:
        if key in xse_hashedscripts_local:
            hash1 = xse_hashedscripts[key]
            hash2 = xse_hashedscripts_local[key]
            if hash1 == hash2:
                pass
            elif hash2 is None:  # Can only be None if not hashed in the first place, meaning it is missing.
                message_list.append(f"❌ CAUTION : {key} Script Extender file is missing from your game Scripts folder! \n-----\n")
                xse_script_missing = True
            else:
                message_list.append(f"[!] CAUTION : {key} Script Extender file is outdated or overriden by another mod! \n-----\n")
                xse_script_mismatch = True

    if xse_script_missing:
        warn_missing = yaml_settings(str, YAML.Game, "Warnings_XSE.Warn_Missing")
        if not isinstance(warn_missing, str):
            raise TypeError
        message_list.append(warn_missing)
    if xse_script_mismatch:
        warn_mismatch = yaml_settings(str, YAML.Game, "Warnings_XSE.Warn_Mismatch")
        if not isinstance(warn_mismatch, str):
            raise TypeError
        message_list.append(warn_mismatch)
    if not xse_script_missing and not xse_script_mismatch:
        message_list.append("✔️ All Script Extender files have been found and accounted for! \n-----\n")

    return "".join(message_list)


# ================================================
# CHECK DOCUMENTS GAME INI FILES & INI SETTINGS
# ================================================
def docs_check_folder() -> str:
    message_list = []
    docs_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_Docs_Name")
    if not isinstance(docs_name, str):
        raise TypeError
    if "onedrive" in docs_name.lower():
        docs_warn = yaml_settings(str, YAML.Main, "Warnings_GAME.warn_docs_path")
        if not isinstance(docs_warn, str):
            raise TypeError
        message_list.append(docs_warn)
    return "".join(message_list)


# =========== CHECK DOCS MAIN INI -> CHECK EXISTENCE & CORRUPTION ===========
def docs_check_ini(ini_name: str) -> str:
    message_list: list[str] = []
    logger.info(f"- - - INITIATED {ini_name} CHECK")
    folder_docs = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")
    docs_name = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.Main_Docs_Name")
    if not isinstance(docs_name, str):
        raise TypeError
    if not (isinstance(folder_docs, str) or folder_docs is None):
        raise TypeError

    ini_file_list = list(Path(folder_docs).glob("*.ini")) if folder_docs else []
    ini_path = Path(folder_docs).joinpath(ini_name) if folder_docs else None
    if ini_path is None:
        raise TypeError
    if any(ini_name.lower() in file.name.lower() for file in ini_file_list):
        try:
            remove_readonly(ini_path)

            INI_config = configparser.ConfigParser()
            INI_config.optionxform = str  # type: ignore[method-assign, assignment]
            INI_config.read(ini_path)
            message_list.append(f"✔️ No obvious corruption detected in {ini_name}, file seems OK! \n-----\n")

            if ini_name.lower() == f"{docs_name.lower()}custom.ini":
                if "Archive" not in INI_config.sections():
                    message_list.extend(["❌ WARNING : Archive Invalidation / Loose Files setting is not enabled. \n",
                                         "  CLASSIC will now enable this setting automatically in the game INI files. \n-----\n"])
                    with contextlib.suppress(configparser.DuplicateSectionError):
                        INI_config.add_section("Archive")
                else:
                    message_list.append("✔️ Archive Invalidation / Loose Files setting is already enabled! \n-----\n")

                INI_config.set("Archive", "bInvalidateOlderFiles", "1")
                INI_config.set("Archive", "sResourceDataDirsFinal", "")

                with ini_path.open("w+", encoding="utf-8", errors="ignore") as ini_file:
                    INI_config.write(ini_file, space_around_delimiters=False)

        except PermissionError:
            message_list.extend([f"[!] CAUTION : YOUR {ini_name} FILE IS SET TO READ ONLY. \n",
                                 "     PLEASE REMOVE THE READ ONLY PROPERTY FROM THIS FILE, \n",
                                 "     SO CLASSIC CAN MAKE THE REQUIRED CHANGES TO IT. \n-----\n"])

        except (configparser.MissingSectionHeaderError, configparser.ParsingError, ValueError, OSError):
            message_list.extend([f"[!] CAUTION : YOUR {ini_name} FILE IS VERY LIKELY BROKEN, PLEASE CREATE A NEW ONE \n",
                                 f"    Delete this file from your Documents/My Games/{docs_name} folder, then press \n",
                                 f"    *Scan Game Files* in CLASSIC to generate a new {ini_name} file. \n-----\n"])
        except configparser.DuplicateOptionError as e:
            message_list.extend([f"[!] ERROR : Your {ini_name} file has duplicate options! \n",
                                 f"    {e} \n-----\n"])
    else:
        if ini_name.lower() == f"{docs_name.lower()}.ini":
            message_list.extend([f"❌ CAUTION : {ini_name} FILE IS MISSING FROM YOUR DOCUMENTS FOLDER! \n",
                                 f"   You need to run the game at least once with {docs_name}Launcher.exe \n",
                                 "    This will create files and INI settings required for the game to run. \n-----\n"])

        if ini_name.lower() == f"{docs_name.lower()}custom.ini":
            with ini_path.open("a", encoding="utf-8", errors="ignore") as ini_file:
                message_list.extend(["❌ WARNING : Archive Invalidation / Loose Files setting is not enabled. \n",
                                     "  CLASSIC will now enable this setting automatically in the game INI files. \n-----\n"])
                customini_config = yaml_settings(str, YAML.Game, "Default_CustomINI")
                if not isinstance(customini_config, str):
                    raise TypeError
                ini_file.write(customini_config)

    return "".join(message_list)


# =========== GENERATE FILE BACKUPS ===========
def main_files_backup() -> None:
    # Got an expired certificate warning after a few tries, maybe there's a better way?
    backup_list = yaml_settings(list[str], YAML.Main, "CLASSIC_AutoBackup")
    game_path = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game")
    xse_log_file = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Docs_File_XSE")
    xse_ver_latest = yaml_settings(str, YAML.Game, f"Game{gamevars["vr"]}_Info.XSE_Ver_Latest")

    if not (isinstance(backup_list, list) and isinstance(xse_ver_latest, str)):
        raise TypeError
    if not (isinstance(game_path, str) or game_path is None):
        raise TypeError
    if not isinstance(xse_log_file, str):
        raise TypeError

    try:
        with open_file_with_encoding(xse_log_file) as xse_log:
            xse_data = xse_log.readlines()
            xse_data_lower = [line.lower() for line in xse_data]
    except FileNotFoundError:
        xse_data_lower = []
        

    # Grab current xse version to create a folder with that name.
    if len(xse_data_lower) > 0:
        line_xse = next(line for _, line in enumerate(xse_data_lower) if "version = " in line)
        split_xse = line_xse.split(" ")
        version_xse = xse_ver_latest

        for index, item in enumerate(split_xse):
            if "version" in item:
                index_xse = int(index + 2)
                version_xse = split_xse[index_xse]
                break

        # If there is no folder for current xse version, create it.
        backup_path = Path(f"CLASSIC Backup/Game Files/{version_xse}") if version_xse else None
        if backup_path:
            backup_path.mkdir(parents=True, exist_ok=True)

            # Backup the file if backup of file does not already exist.
            game_files = list(Path(game_path).glob("*.*")) if game_path else []
            backup_files = [file.name for file in backup_path.glob("*.*")]
    
            for file in game_files:
                if file.name not in backup_files and any(file.name in item for item in backup_list):
                    destination_file = backup_path / file.name
                    shutil.copy2(file, destination_file)

# =========== GENERATE MAIN RESULTS ===========
def main_combined_result() -> str:
    combined_return = [game_check_integrity(), xse_check_integrity(), xse_check_hashes(), docs_check_folder(),
                       docs_check_ini(f"{gamevars["game"]}.ini"), docs_check_ini(f"{gamevars["game"]}Custom.ini"), docs_check_ini(f"{gamevars["game"]}Prefs.ini")]
    return "".join(combined_return)


def main_generate_required() -> None:
    configure_logging()
    classic_data_extract()
    classic_generate_files()
    classic_ver = yaml_settings(str, YAML.Main, "CLASSIC_Info.version")
    game_name = yaml_settings(str, YAML.Game, "Game_Info.Main_Root_Name")
    if not (isinstance(classic_ver, str) and isinstance(game_name, str)):
        raise TypeError
    print(f"Hello World! | Crash Log Auto Scanner & Setup Integrity Checker | {classic_ver} | {game_name}")
    print("REMINDER: COMPATIBLE CRASH LOGS MUST START WITH 'crash-' AND MUST HAVE .log EXTENSION \n")
    print("❓ PLEASE WAIT WHILE CLASSIC CHECKS YOUR SETTINGS AND GAME SETUP...")
    logger.debug(f"> > > STARTED {classic_ver}")

    game_path = yaml_settings(str, YAML.Game_Local, f"Game{gamevars["vr"]}_Info.Root_Folder_Game")

    if not game_path:
        docs_path_find()
        docs_generate_paths()
        game_path_find()
        game_generate_paths()
    else:
        main_files_backup()

    print("✔️ ALL CLASSIC AND GAME SETTINGS CHECKS HAVE BEEN PERFORMED!")
    print("    YOU CAN NOW SCAN YOUR CRASH LOGS, GAME AND/OR MOD FILES \n")


yaml_cache: YamlSettingsCache | None = None
manual_docs_gui: ManualDocsPath | None = None
game_path_gui: GamePathEntry | None = None
gui_mode: bool = False


def initialize(is_gui: bool = False) -> None:
    global gui_mode, yaml_cache, manual_docs_gui, game_path_gui  # noqa: PLW0603

    yaml_cache = YamlSettingsCache()
    gamevars["vr"] = "VR" if classic_settings(bool, "VR Mode") else ""
    gui_mode = is_gui
    if gui_mode:
        manual_docs_gui = ManualDocsPath()
        game_path_gui = GamePathEntry()


if __name__ == "__main__":  # AKA only autorun / do the following when NOT imported.
    initialize()
    main_generate_required()
    os.system("pause")
