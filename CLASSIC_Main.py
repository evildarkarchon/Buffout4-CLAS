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
from io import TextIOWrapper
from pathlib import Path
from typing import Literal, TypedDict

import aiohttp
import chardet
import ruamel.yaml
from PySide6.QtCore import QObject, Signal

with contextlib.suppress(ImportError):
    import winreg

""" AUTHOR NOTES (POET): ❓ ❌ ✔️
    ❓ REMINDER: 'shadows x from outer scope' means the variable name repeats both in the func and outside all other func.
    ❓ Comments marked as RESERVED in all scripts are intended for future updates or tests, do not edit / move / remove.
    ❓ (..., encoding="utf-8", errors="ignore") needs to go with every opened file because of unicode & charmap errors.
    ❓ import shelve if you want to store persistent data that you do not want regular users to access or modify.
    ❓ Globals are generally used to standardize game paths and INI files naming conventions.
    -----
    CO-AUTHOR NOTES (EvilDarkArchon):
    ❓ We're going to have to special-case (or disable) Starfield Script Extender update checks because it's on Nexus, not silverlock.org.
"""

type YAMLValue = dict[str, list[str] | str | int] | list[str] | str | int
type YAMLValueOptional = YAMLValue | None
type GameID = Literal["Fallout4", "Skyrim", "Starfield"] # Entries must correspond to the game's My Games folder name.

class GameVars(TypedDict):
    game: GameID
    vr: Literal["VR", ""]

gamevars: GameVars = {
    "game": "Fallout4",
    "vr": ""
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
            yaml_settings(f"CLASSIC Data/CLASSIC {gamevars['game']} Local.yaml", f"Game{gamevars['vr']}_Info.Root_Folder_Docs", str(manual_docs))
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
            yaml_settings(f"CLASSIC Data/CLASSIC {gamevars['game']} Local.yaml", f"Game{gamevars['vr']}_Info.Root_Folder_Game", str(game_path))
        else:
            print(f"'{path}' is not a valid or existing directory path. Please try again.")
            self.game_path_signal.emit()

@contextlib.contextmanager
def open_file_with_encoding(file_path: Path | str | os.PathLike) -> Iterator[TextIOWrapper]:
    """Read only file open with encoding detection. Only for text files."""

    if not isinstance(file_path, Path):
        file_path = Path(file_path)
    with file_path.open("rb") as f:
        raw_data = f.read()
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
        self.cache: dict[Path, ruamel.yaml.CommentedMap] = {}
        self.file_mod_times: dict[Path, float] = {}

    def load_yaml(self, yaml_path: str | os.PathLike) -> dict[str, YAMLValue]:
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
                with yaml_path.open('r', encoding='utf-8') as yaml_file:
                    yaml = ruamel.yaml.YAML()
                    yaml.indent(offset=2)
                    yaml.width = 300
                    self.cache[yaml_path] = yaml.load(yaml_file)

        return self.cache.get(yaml_path, {})

    def get_setting(self, yaml_path: Path, key_path: str, new_value: str | bool | None = None) -> YAMLValue | None:
        data = self.load_yaml(yaml_path)
        keys = key_path.split('.') if isinstance(key_path, str) else key_path
        value = data

        # If new_value is provided, update the value
        if new_value is not None:
            for key in keys[:-1]:
                value: dict[str, YAMLValue] = value.setdefault(key, {}) # type: ignore
            value[keys[-1]] = new_value

            # Write changes back to the YAML file
            with yaml_path.open("w", encoding="utf-8") as yaml_file:
                yaml = ruamel.yaml.YAML()
                yaml.indent(offset=2)
                yaml.width = 300
                yaml.dump(data, yaml_file)

            # Update the cache
            self.cache[yaml_path] = data # type: ignore
            return new_value

        # Traverse YAML structure to get value
        for key in keys:
            if key in value:
                value = value[key] # type: ignore
            else:
                return None  # Key not found
        if value is None and "Path" not in key_path:  # type: ignore  # Error me if I mistype or screw up the value grab.
            print(f"❌ ERROR (yaml_settings) : Trying to grab a None value for : '{key_path}'") # Despite what the type checker says, this code is reachable.
        return value # type: ignore

# Function compatible with the old interface
def yaml_settings(yaml_path: str, key_path: str, new_value: str | bool | None = None) -> YAMLValue | None:
    if yaml_cache is None:
        raise TypeError("CMain not initialized")
    return yaml_cache.get_setting(Path(yaml_path), key_path, new_value)

def classic_settings(setting: str | None = None) -> str | bool | None:
    settings_path = Path("CLASSIC Settings.yaml")
    if not settings_path.exists():
        default_settings = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Info.default_settings")
        if not isinstance(default_settings, str):
            raise ValueError("Invalid Default Settings in 'CLASSIC Main.yaml'")

        with settings_path.open("w", encoding="utf-8") as file:
            file.write(default_settings)
    if setting:
        setting_value = yaml_settings(str(settings_path), f"CLASSIC_Settings.{setting}")
        if not isinstance(setting_value, str) and not isinstance(setting_value, bool) and setting_value is not None:
            raise ValueError(f"Invalid value for '{setting}' in '{settings_path.name}'")

        if setting_value is None and "Path" not in setting:  # Error me if I make a stupid mistype.
            print(f"❌ ERROR (classic_settings) : Trying to grab a None value for : '{setting}'")
        return setting_value
    return None


# ================================================
# CREATE REQUIRED FILES, SETTINGS & UPDATE CHECK
# ================================================
def classic_generate_files() -> None:  # Other paths will be auto generated by the code.
    ignore_path = Path("CLASSIC Ignore.yaml")
    if not ignore_path.exists():
        default_ignorefile: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Info.default_ignorefile") # type: ignore
        with ignore_path.open("w", encoding="utf-8") as file:
            file.write(default_ignorefile)

    local_path = Path(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml")
    if not local_path.exists():
        default_yaml: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Info.default_localyaml") # type: ignore
        with local_path.open("w", encoding="utf-8", errors="ignore") as file:
            file.write(default_yaml)


def classic_data_extract() -> None:
    def open_zip() -> zipfile.ZipFile:

        exe = sys.executable if getattr(sys, "frozen", False) else __file__
        exedir = Path(exe).parent

        if datafile := tuple(exedir.rglob("CLASSIC Data.zip", case_sensitive=False)):
            return zipfile.ZipFile(str(datafile[0]), "r")
        raise FileNotFoundError
    try:
        if not Path("CLASSIC Data/databases/CLASSIC Main.yaml").exists():
            with open_zip() as zip_data:
                zip_data.extractall("CLASSIC Data")
    except FileNotFoundError:
        print("❌ ERROR : UNABLE TO FIND CLASSIC Data.zip! This archive is required for CLASSIC to function.")
        print("Please ensure that you have extracted all CLASSIC files into the same folder after downloading.")
        raise

async def classic_update_check(quiet: bool = False, gui_request: bool = True) -> bool:
    logger.debug("- - - INITIATED UPDATE CHECK")
    if classic_settings("Update Check") or gui_request:
        classic_local: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Info.version")  # type: ignore
        if not quiet:
            print("❓ (Needs internet connection) CHECKING FOR NEW CLASSIC VERSIONS...")
            sys.stdout.flush()
            print("   (You can disable this check in the EXE or CLASSIC Settings.yaml) \n")
            sys.stdout.flush()
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get("https://api.github.com/repos/evildarkarchon/CLASSIC-Fallout4/releases/latest") as response:
                    if response.status != 200:
                        response.raise_for_status()
                    response_json = await response.json()  # Await the JSON response

                    # Now you can access items in the JSON response
                    classic_ver_received = response_json["name"]

                    if classic_ver_received == classic_local:
                        if not quiet:
                            print(f"Your CLASSIC Version: {classic_local}\nNewest CLASSIC Version: {classic_ver_received}\n")
                            sys.stdout.flush()
                            print("✔️ You have the latest version of CLASSIC! \n")
                            sys.stdout.flush()
                        return True

                    if not quiet:
                        print(yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", f"CLASSIC_Interface.update_warning_{gamevars["game"]}"))
                        sys.stdout.flush()
            except (ValueError, OSError, aiohttp.ClientError) as err:
                if not quiet:
                    print(err)
                    sys.stdout.flush()
                    print(yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", f"CLASSIC_Interface.update_unable_{gamevars["game"]}"))
                    sys.stdout.flush()
    elif not quiet:
        print("\n❌ NOTICE: UPDATE CHECK IS DISABLED IN CLASSIC Settings.yaml \n")
        sys.stdout.flush()
        print("===============================================================================")
        sys.stdout.flush()
    return False


# ================================================
# CHECK DEFAULT DOCUMENTS & GAME FOLDERS / FILES
# ================================================
# =========== CHECK DOCUMENTS FOLDER PATH -> GET GAME DOCUMENTS FOLDER ===========
def docs_path_find() -> None:
    if manual_docs_gui is None:
        raise TypeError("CMain not initialized")

    logger.debug("- - - INITIATED DOCS PATH CHECK")
    docs_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_Docs_Name")  # type: ignore

    def get_windows_docs_path() -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Shell Folders") as key: # type: ignore
                documents_path = Path(winreg.QueryValueEx(key, "Personal")[0])  # type: ignore
        except OSError:
            # Fallback to a default path if registry key is not found
            documents_path = Path.home() / "Documents"

        # Construct the full path
        win_docs = documents_path / "My Games" / docs_name

        # Update the YAML settings (assuming this function exists)
        yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(win_docs))

    def get_linux_docs_path() -> None:
        game_sid: int = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_SteamID")  # type: ignore
        libraryfolders_path = Path.home().joinpath(".local", "share", "Steam", "steamapps", "common", "libraryfolders.vdf")
        if libraryfolders_path.is_file():
            library_path = Path()
            with libraryfolders_path.open(encoding="utf-8", errors="ignore") as steam_library_raw:
                steam_library = steam_library_raw.readlines()
            for library_line in steam_library:
                if "path" in library_line:
                    library_path = Path(library_line.split('"')[3])
                if str(game_sid) in library_line:
                    library_path = library_path.joinpath("steamapps")
                    linux_docs = library_path.joinpath("compatdata", str(game_sid), "pfx", "drive_c", "users", "steamuser", "My Documents", "My Games", docs_name)
                    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(linux_docs))

    def get_manual_docs_path() -> None:
        if manual_docs_gui is None:
            raise TypeError("CMain not initialized")

        if gui_mode:
            manual_docs_gui.manual_docs_path_signal.emit()
            return
        print(f"> > > PLEASE ENTER THE FULL DIRECTORY PATH WHERE YOUR {docs_name}.ini IS LOCATED < < <")
        while True:
            input_str = input(f"(EXAMPLE: C:/Users/Zen/Documents/My Games/{docs_name} | Press ENTER to confirm.)\n> ").strip()
            input_path = Path(input_str)
            if input_str and input_path.is_dir():
                print(f"You entered: '{input_str}' | This path will be automatically added to CLASSIC Settings.yaml")
                yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(input_path))
                break

            print(f"'{input_str}' is not a valid or existing directory path. Please try again.")

    # =========== CHECK IF GAME DOCUMENTS FOLDER PATH WAS GENERATED AND FOUND ===========
    docs_path: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")  # type: ignore
    if docs_path is None:
        if platform.system() == "Windows":
            get_windows_docs_path()
        else:
            get_linux_docs_path()

    docs_path = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")  # type: ignore
    try:  # In case .exists() complains about checking a None value.
        if docs_path and not Path(docs_path).exists():
            if gui_mode:
                manual_docs_gui.manual_docs_path_signal.emit()
            else:
                get_manual_docs_path()
    except (ValueError, OSError):
        if gui_mode:
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
            if f"{gamevars['game']}.ini" in file.name:
                print(f"You entered: '{path}' | This path will be automatically added to CLASSIC Settings.yaml")
                manual_docs = Path(path)
                yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs", str(manual_docs))
                file_found = True
                break
        if not file_found:
            print(f"❌ ERROR : NO {gamevars['game']}.ini FILE FOUND IN '{path}'! Please try again.")
            manual_docs_gui.manual_docs_path_signal.emit()
    else:
        print(f"'{path}' is not a valid or existing directory path. Please try again.")
        manual_docs_gui.manual_docs_path_signal.emit()

def docs_generate_paths() -> None:
    logger.debug("- - - INITIATED DOCS PATH GENERATION")
    xse_acronym: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Acronym")  # type: ignore
    xse_acronym_base: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Game_Info.XSE_Acronym")  # type: ignore
    docs_path: Path = Path(yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs"))  # type: ignore

    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_Folder_XSE", str(docs_path.joinpath(xse_acronym_base)))
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_PapyrusLog", str(docs_path.joinpath("Logs/Script/Papyrus.0.log")))
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_WryeBashPC", str(docs_path.joinpath("ModChecker.html")))
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_XSE", str(docs_path.joinpath(xse_acronym_base, f"{xse_acronym.lower()}.log")))


# =========== CHECK DOCUMENTS XSE FILE -> GET GAME ROOT FOLDER PATH ===========
def game_path_find() -> None:
    def get_game_registry_path() -> Path | None:
        try:
            # Open the registry key
            reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Bethesda Softworks\{gamevars['game']}{gamevars['vr']}")  # type: ignore
            # Query the 'installed path' value
            path, _ = winreg.QueryValueEx(reg_key, "installed path") # type: ignore
            winreg.CloseKey(reg_key) # type: ignore
            outpath = Path(path) if path else None
        except (UnboundLocalError, FileNotFoundError, OSError):
            return None
        else:
            return outpath

    game_path = get_game_registry_path()

    if game_path and game_path.is_dir() and game_path.joinpath(f"{gamevars['game']}{gamevars['vr']}.exe").is_file():
        yaml_settings(f"CLASSIC Data/CLASSIC {gamevars['game']} Local.yaml", f"Game{gamevars['vr']}_Info.Root_Folder_Game", str(game_path))
        return

    if game_path_gui is None:
        raise TypeError("CMain not initialized")

    logger.debug("- - - INITIATED GAME PATH CHECK")
    xse_file: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_XSE")  # type: ignore
    xse_acronym: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Acronym")  # type: ignore
    xse_acronym_base: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Game_Info.XSE_Acronym")  # type: ignore
    game_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_Root_Name")  # type: ignore

    if not game_path and xse_file and Path(xse_file).is_file():
        with open_file_with_encoding(xse_file) as LOG_Check:
            Path_Check = LOG_Check.readlines()
            for logline in Path_Check:
                if logline.startswith("plugin directory"):
                    logline = logline.split("=", maxsplit=1)[1].strip().replace(f"\\Data\\{xse_acronym_base}\\Plugins", "").replace("\n", "")
                    game_path = Path(logline)
                    if not logline or not game_path.exists():
                        if gui_mode:
                            game_path_gui.game_path_signal.emit()
                            if not game_path.joinpath(f"{gamevars['game']}{gamevars['vr']}.exe").exists():
                                print(f"❌ ERROR : NO {gamevars['game']}{gamevars['vr']}.exe FILE FOUND IN '{game_path}'! Please try again.")
                                game_path_gui.game_path_signal.emit()
                        else:
                            print(f"> > PLEASE ENTER THE FULL DIRECTORY PATH WHERE YOUR {game_name} IS LOCATED < <")
                            path_input = input(fr"(EXAMPLE: C:\Steam\steamapps\common\{game_name} | Press ENTER to confirm.)\n> ")
                            print(f"You entered: {path_input} | This path will be automatically added to CLASSIC Settings.yaml")
                            game_path = Path(path_input.strip())

                    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Game", str(game_path))
    elif not game_path and xse_file and not Path(xse_file).is_file(): # type: ignore
        print(f"❌ CAUTION : THE {xse_acronym.lower()}.log FILE IS MISSING FROM YOUR GAME DOCUMENTS FOLDER! \n")
        print(f"   You need to run the game at least once with {xse_acronym.lower()}_loader.exe \n")
        print("    After that, try running CLASSIC again! \n-----\n")


def game_generate_paths() -> None:
    logger.debug("- - - INITIATED GAME PATH GENERATION")

    game_path: str = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Game")  # type: ignore
    yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Acronym")  # type: ignore
    xse_acronym_base: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Game_Info.XSE_Acronym")  # type: ignore

    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_Folder_Data", fr"{game_path}\Data")
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_Folder_Scripts", fr"{game_path}\Data\Scripts")
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_Folder_Plugins", fr"{game_path}\Data\{xse_acronym_base}\Plugins")
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_File_SteamINI", fr"{game_path}\steam_api.ini")
    yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_File_EXE", fr"{game_path}\{gamevars["game"]}{gamevars["vr"]}.exe")
    match gamevars["game"]:
        case "Fallout4" if not gamevars["vr"]:
            yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", "Game_Info.Game_File_AddressLib", fr"{game_path}\Data\{xse_acronym_base}\plugins\version-1-10-163-0.bin")
        case "Fallout4" if gamevars["vr"]:
            yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", "GameVR_Info.Game_File_AddressLib", fr"{game_path}\Data\{xse_acronym_base}\plugins\version-1-2-72-0.csv")


# =========== CHECK GAME EXE FILE -> GET PATH AND HASHES ===========
def game_check_integrity() -> str:
    message_list = []
    logger.debug("- - - INITIATED GAME INTEGRITY CHECK")

    steam_ini_local: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_File_SteamINI")  # type: ignore
    exe_hash_old: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.EXE_HashedOLD")  # type: ignore
    # exe_hash_new: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.EXE_HashedNEW")  # type: ignore  | RESERVED FOR 2023 UPDATE
    game_exe_local: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_File_EXE")  # type: ignore
    root_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_Root_Name")  # type: ignore

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
            root_warn: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "Warnings_GAME.warn_root_path")  # type: ignore
            message_list.append(root_warn)

    return "".join(message_list)


# =========== CHECK GAME XSE SCRIPTS -> GET PATH AND HASHES ===========
def xse_check_integrity() -> str:  # RESERVED | NEED VR HASH/FILE CHECK
    failed_list: list = []
    message_list: list[str] = []
    logger.debug("- - - INITIATED XSE INTEGRITY CHECK")

    catch_errors: list[str] = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "catch_log_errors") # type: ignore
    xse_acronym: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Acronym") # type: ignore
    xse_log_file: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_XSE") # type: ignore
    xse_full_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_FullName") # type: ignore
    xse_ver_latest:str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Ver_Latest") # type: ignore
    adlib_file: str | Path | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_File_AddressLib") #type: ignore

    match adlib_file:
        case str() | Path():
            if Path(adlib_file).exists():
                message_list.append("✔️ REQUIRED: *Address Library* for Script Extender is installed! \n-----\n")
            else:
                message_list.append(yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Warnings_MODS.Warn_ADLIB_Missing"))  # type: ignore
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
                    message_list.append(yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Warnings_XSE.Warn_Outdated")) # type: ignore
                for line in xse_data:
                    if any(item.lower() in line.lower() for item in catch_errors):
                        failed_list.append(line)  # noqa: PERF401

                if failed_list:
                    message_list.append(f"#❌ CAUTION : {xse_acronym}.log REPORTS THE FOLLOWING ERRORS #\n")
                    for elem in failed_list:
                        message_list.append(f"ERROR > {elem.strip()} \n-----\n")  # noqa: PERF401
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
    xse_hashedscripts: dict[str, str] = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_HashedScripts") # type: ignore
    game_folder_scripts: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Game_Folder_Scripts") # type: ignore

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
        message_list.append(yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Warnings_XSE.Warn_Missing")) # type: ignore
    if xse_script_mismatch:
        message_list.append(yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Warnings_XSE.Warn_Mismatch")) # type: ignore
    if not xse_script_missing and not xse_script_mismatch:
        message_list.append("✔️ All Script Extender files have been found and accounted for! \n-----\n")

    return "".join(message_list)


# ================================================
# CHECK DOCUMENTS GAME INI FILES & INI SETTINGS
# ================================================
def docs_check_folder() -> str:
    message_list = []
    docs_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_Docs_Name")  # type: ignore
    if "onedrive" in docs_name.lower():
        docs_warn: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "Warnings_GAME.warn_docs_path")  # type: ignore
        message_list.append(docs_warn)
    return "".join(message_list)


# =========== CHECK DOCS MAIN INI -> CHECK EXISTENCE & CORRUPTION ===========
def docs_check_ini(ini_name: str) -> str:
    message_list: list[str] = []
    logger.info(f"- - - INITIATED {ini_name} CHECK")
    folder_docs: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Docs")  # type: ignore
    docs_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.Main_Docs_Name")  # type: ignore

    ini_file_list = list(Path(folder_docs).glob("*.ini")) # type: ignore
    ini_path = Path(folder_docs).joinpath(ini_name) # type: ignore
    if any(ini_name.lower() in file.name.lower() for file in ini_file_list):
        try:
            remove_readonly(ini_path)

            INI_config = configparser.ConfigParser()
            INI_config.optionxform = str # type: ignore
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
                customini_config: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Default_CustomINI")  # type: ignore
                ini_file.write(customini_config)

    return "".join(message_list)


# =========== GENERATE FILE BACKUPS ===========
def main_files_backup() -> None:
    # Got an expired certificate warning after a few tries, maybe there's a better way?
    backup_list: list[str] = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_AutoBackup")  # type: ignore
    game_path: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Game")  # type: ignore
    xse_log_file: str | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Docs_File_XSE")  # type: ignore
    xse_ver_latest: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", f"Game{gamevars["vr"]}_Info.XSE_Ver_Latest")  # type: ignore
    with open_file_with_encoding(xse_log_file) as xse_log: # type: ignore
        xse_data = xse_log.readlines()
    # Grab current xse version to create a folder with that name.
    line_xse = next(line for _, line in enumerate(xse_data) if "version = " in line.lower())
    split_xse = line_xse.split(" ")
    version_xse = xse_ver_latest
    for index, item in enumerate(split_xse):
        if "version" in item.lower():
            index_xse = int(index + 2)
            version_xse = split_xse[index_xse]
            break

    # If there is no folder for current xse version, create it.
    backup_path = Path(f"CLASSIC Backup/Game Files/{version_xse}")
    backup_path.mkdir(parents=True, exist_ok=True)
    # Backup the file if backup of file does not already exist.
    game_files = list(Path(game_path).glob("*.*")) # type: ignore
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
    classic_ver: str = yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Info.version")  # type: ignore
    game_name: str = yaml_settings(f"CLASSIC Data/databases/CLASSIC {gamevars["game"]}.yaml", "Game_Info.Main_Root_Name")  # type: ignore
    print(f"Hello World! | Crash Log Auto Scanner & Setup Integrity Checker | {classic_ver} | {game_name}")
    print("REMINDER: COMPATIBLE CRASH LOGS MUST START WITH 'crash-' AND MUST HAVE .log EXTENSION \n")
    print("❓ PLEASE WAIT WHILE CLASSIC CHECKS YOUR SETTINGS AND GAME SETUP...")
    logger.debug(f"> > > STARTED {classic_ver}")

    game_path: YAMLValue | None = yaml_settings(f"CLASSIC Data/CLASSIC {gamevars["game"]} Local.yaml", f"Game{gamevars["vr"]}_Info.Root_Folder_Game")  # type: ignore

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

    # Instantiate a global cache object
    yaml_cache = YamlSettingsCache()
    gamevars["vr"] = "VR" if classic_settings("VR Mode") else ""
    manual_docs_gui = ManualDocsPath()
    game_path_gui = GamePathEntry()
    gui_mode = is_gui


if __name__ == "__main__":  # AKA only autorun / do the following when NOT imported.
    initialize()
    main_generate_required()
    os.system("pause")
