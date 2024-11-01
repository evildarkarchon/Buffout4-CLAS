import io
import os
import shutil
import struct
import subprocess
from collections.abc import ItemsView
from configparser import NoOptionError, NoSectionError
from pathlib import Path
from typing import Any, Literal, TypedDict

import chardet
import iniparse
import tomlkit
from bs4 import BeautifulSoup, PageElement

import CLASSIC_Main as CMain

# For comparing results across runs.
# Skips moving/editing files; outputs to 'CLASSIC GFS Report.md' instead of console.
TEST_MODE = False


# ================================================
# DEFINE MAIN FILE / YAML FUNCTIONS
# ================================================
class ConfigFile(TypedDict):
    encoding: str
    path: Path
    settings: iniparse.ConfigParser
    text: str


class ConfigFileCache:
    _config_files: dict[str, Path]
    _config_file_cache: dict[str, ConfigFile]
    duplicate_files: dict[str, list[Path]]
    _game_root_path: Path | None

    def __init__(self) -> None:
        self._config_files = {}
        self._config_file_cache = {}
        self.duplicate_files = {}

        self._game_root_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Root_Folder_Game")
        if self._game_root_path is None:
            # TODO: Check if this needs to raise or return an error message instead. (See also: TODO in scan_mod_inis)
            raise FileNotFoundError

        for path, _dirs, files in self._game_root_path.walk():
            for file in files:
                file_lower = file.lower()
                # if not file_lower.endswith((".ini", ".conf")):
                if not file_lower.endswith(".ini") and file_lower != "dxvk.conf":
                    continue

                file_path = path / file
                if file_lower in self._config_files:
                    if file_lower in self.duplicate_files:
                        self.duplicate_files[file_lower].append(file_path)
                    else:
                        self.duplicate_files[file_lower] = [file_path]
                    continue

                self._config_files[file_lower] = file_path

    def __contains__(self, file_name_lower: str) -> bool:
        return file_name_lower in self._config_files

    # TODO: Useful for checking how many INIs found
    # def __bool__(self) -> bool:
    #     return bool(self._config_files)

    # def __len__(self) -> int:
    #     return len(self._config_files)

    def __getitem__(self, file_name_lower: str) -> Path:
        return self._config_files[file_name_lower]

    def _load_config(self, file_name_lower: str) -> None:
        if file_name_lower not in self._config_files:
            raise FileNotFoundError

        if file_name_lower in self._config_file_cache:
            # Delete the cache and reload the file
            del self._config_file_cache[file_name_lower]

        file_path = self._config_files[file_name_lower]
        with file_path.open("rb") as f:
            file_bytes = f.read()
        file_encoding = chardet.detect(file_bytes)["encoding"] or "utf-8"
        file_text = file_bytes.decode(file_encoding)
        config = iniparse.ConfigParser()
        config.readfp(io.StringIO(file_text, newline=None))

        self._config_file_cache[file_name_lower] = {
            "encoding": file_encoding,
            "path": file_path,
            "settings": config,
            "text": file_text,
        }

    def get[T](self, value_type: type[T], file_name_lower: str, section: str, setting: str) -> T | None:
        """Get the value of a setting, or None if the file or setting doesn't exist."""
        if value_type is not str and value_type is not bool and value_type is not int and value_type is not float:
            raise NotImplementedError

        if file_name_lower not in self._config_files:
            return None

        if file_name_lower not in self._config_file_cache:
            try:
                self._load_config(file_name_lower)
            except FileNotFoundError:
                CMain.logger.error(f"ERROR: Config file not found - {file_name_lower}")
                return None

        config = self._config_file_cache[file_name_lower]["settings"]

        if not config.has_section(section):
            CMain.logger.error(f"ERROR: Section '{section}' does not exist in '{self._config_files[file_name_lower]}'")
            return None

        if not config.has_option(section, setting):
            CMain.logger.error(f"ERROR: Key '{setting}' does not exist in section '{section}' of '{self._config_files[file_name_lower]}'")
            return None

        try:
            if value_type is str:
                return config.get(section, setting)
            if value_type is bool:
                return config.getboolean(section, setting)
            if value_type is int:
                return config.getint(section, setting)
            if value_type is float:
                return config.getfloat(section, setting)
            raise NotImplementedError
        except ValueError as e:
            CMain.logger.error(f"ERROR: Unexpected value type - {e}")
            return None
        except (NoSectionError, NoOptionError):
            return None

    def get_strict[T](self, value_type: type[T], file: str, section: str, setting: str) -> T:
        """Get the value of a setting, or a falsy default if the file or setting doesn't exist."""
        value = self.get(value_type, file, section, setting)
        if value is not None:
            return value
        if value_type is str:
            return ""  # type: ignore[return-value]
        if value_type is bool:
            return False  # type: ignore[return-value]
        if value_type is int:
            return 0  # type: ignore[return-value]
        if value_type is float:
            return 0.0  # type: ignore[return-value]
        raise NotImplementedError

    def set[T](self, value_type: type[T], file_name_lower: str, section: str, setting: str, value: T) -> None:
        if value_type is not str and value_type is not bool and value_type is not int and value_type is not float:
            raise NotImplementedError

        if file_name_lower not in self._config_file_cache:
            try:
                self._load_config(file_name_lower)
            except FileNotFoundError:
                CMain.logger.error(f"ERROR: Config file not found - {file_name_lower}")
                return

        cache = self._config_file_cache[file_name_lower]
        config = cache["settings"]
        value = ("true" if value else "false") if value_type is bool else str(value)  # type: ignore[assignment]
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, setting, value)

        if not TEST_MODE:
            with cache["path"].open("w", encoding=cache["encoding"], newline="") as f:
                config.write(f)

    def has(self, file_name_lower: str, section: str, setting: str) -> bool:
        if file_name_lower not in self._config_files:
            return False
        try:
            if file_name_lower not in self._config_file_cache:
                self._load_config(file_name_lower)
            config = self._config_file_cache[file_name_lower]["settings"]
            return config.has_option(section, setting)
        except (FileNotFoundError, NoSectionError):
            return False

    def items(self) -> ItemsView[str, Path]:
        return self._config_files.items()


def mod_toml_config(toml_path: Path, section: str, key: str, new_value: str | bool | int | None = None) -> Any | None:
    """Read the TOML file"""
    with CMain.open_file_with_encoding(toml_path) as toml_file:
        data = tomlkit.parse(toml_file.read())

    with toml_path.open("rb") as f:
        file_bytes = f.read()
    file_encoding = chardet.detect(file_bytes)["encoding"] or "utf-8"
    file_text = file_bytes.decode(file_encoding)
    data = tomlkit.parse(file_text)

    if section not in data or key not in data[section]:  # pyright: ignore[reportOperatorIssue]
        return None
    current_value = data[section][key]  # pyright: ignore[reportIndexIssue]

    # If a new value is provided, update the key
    if new_value is not None:
        current_value = new_value
        data[section][key] = new_value  # pyright: ignore[reportIndexIssue]
        if not TEST_MODE:
            with toml_path.open("w", encoding=file_encoding, newline="") as toml_file:
                toml_file.write(data.as_string())
    return current_value


# ================================================
# CHECK BUFFOUT CONFIG SETTINGS
# ================================================
def check_crashgen_settings() -> str:
    message_list: list[str] = []
    plugins_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Game_Folder_Plugins")
    crashgen_name_setting = CMain.yaml_settings(str, CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.CRASHGEN_LogName")
    crashgen_name = crashgen_name_setting if isinstance(crashgen_name_setting, str) else ""

    crashgen_toml_og = plugins_path / "Buffout4/config.toml" if plugins_path else None
    crashgen_toml_vr = plugins_path / "Buffout4.toml" if plugins_path else None
    if crashgen_toml_og and crashgen_toml_og.is_file():
        crashgen_toml_main = crashgen_toml_og
    elif crashgen_toml_vr and crashgen_toml_vr.is_file():
        crashgen_toml_main = crashgen_toml_vr
    else:
        raise FileNotFoundError("Buffout4.toml not found in the plugins folder.")

    if (crashgen_toml_og and crashgen_toml_og.is_file()) and (crashgen_toml_vr and crashgen_toml_vr.is_file()):
        message_list.extend((
            f"# ❌ CAUTION : BOTH VERSIONS OF {crashgen_name.upper()} TOML SETTINGS FILES WERE FOUND! #\n",
            f"When editing {crashgen_name} toml settings, make sure you are editing the correct file.\n",
            f"Please recheck your {crashgen_name} installation and delete any obsolete files.\n-----\n",
        ))

    xse_files: set[str] = {file.name.lower() for file in plugins_path.iterdir()} if plugins_path else set()
    Has_XCell = "x-cell-fo4.dll" in xse_files
    Has_BakaScrapHeap = "bakascrapheap.dll" in xse_files

    if not crashgen_toml_main:
        message_list.extend((
            f"# [!] NOTICE : Unable to find the {crashgen_name} config file, settings check will be skipped. #\n",
            f"  To ensure this check doesn't get skipped, {crashgen_name} has to be installed manually.\n",
            "  [ If you are using Mod Organizer 2, you need to run CLASSIC through a shortcut in MO2. ]\n-----\n",
        ))
        return "".join(message_list)

    if (
        xse_files
        and ("achievements.dll" in xse_files or "achievementsmodsenablerloader.dll" in xse_files)
        and mod_toml_config(crashgen_toml_main, "Patches", "Achievements")
    ):
        message_list.extend((
            "# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE #\n",
            f"    Auto Scanner will change this parameter to FALSE to prevent conflicts with {crashgen_name}.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "Achievements", False)
    else:
        message_list.append(f"✔️ Achievements parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if Has_BakaScrapHeap and mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager"):
        message_list.extend((
            f"# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with {crashgen_name} #\n",
            f" FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with {crashgen_name}.\n-----\n",
        ))
        if not Has_XCell:
            mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager", True)
    elif Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager"):
        message_list.extend((
            "# ❌ CAUTION : The X-Cell Mod is installed, but MemoryManager parameter is set to TRUE #\n",
            "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager", False)
    else:
        message_list.append(f"✔️ Memory Manager parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "HavokMemorySystem"):
        message_list.extend((
            "# ❌ CAUTION : The X-Cell Mod is installed, but HavokMemorySystem parameter is set to TRUE #\n",
            "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "HavokMemorySystem", False)
    else:
        message_list.append(f"✔️ HavokMemorySystem parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "BSTextureStreamerLocalHeap"):
        message_list.extend((
            "# ❌ CAUTION : The X-Cell Mod is installed, but BSTextureStreamerLocalHeap parameter is set to TRUE #\n",
            "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "BSTextureStreamerLocalHeap", False)
    else:
        message_list.append(f"✔️ BSTextureStreamerLocalHeap parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "ScaleformAllocator"):
        message_list.extend((
            "# ❌ CAUTION : The X-Cell Mod is installed, but ScaleformAllocator parameter is set to TRUE #\n",
            "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "ScaleFormAllocator", False)
    else:
        message_list.append(f"✔️ ScaleformAllocator parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "SmallBlockAllocator"):
        message_list.extend((
            "# ❌ CAUTION : The X-Cell Mod is installed, but SmallBlockAllocator parameter is set to TRUE #\n",
            "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Patches", "SmallBlockAllocator", False)
    else:
        message_list.append(f"✔️ SmallBlockAllocator parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    if xse_files and mod_toml_config(crashgen_toml_main, "Compatibility", "F4EE") and any("f4ee" in file for file in xse_files):
        message_list.extend((
            "# ❌ CAUTION : Looks Menu is installed, but F4EE parameter under [Compatibility] is set to FALSE #\n",
            "    Auto Scanner will change this parameter to TRUE to prevent bugs and crashes from Looks Menu.\n-----\n",
        ))
        mod_toml_config(crashgen_toml_main, "Compatibility", "F4EE", True)
    else:
        message_list.append(f"✔️ F4EE (Looks Menu) parameter is correctly configured in your {crashgen_name} settings!\n-----\n")

    return "".join(message_list)


# ================================================
# CHECK ERRORS IN LOG FILES FOR GIVEN FOLDER
# ================================================
def check_log_errors(folder_path: Path | str) -> str:
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)
    catch_errors_setting = CMain.yaml_settings(list[str], CMain.YAML.Main, "catch_log_errors")
    ignore_logs_list_setting = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_files")
    ignore_logs_errors_setting = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_errors")

    catch_errors = catch_errors_setting if isinstance(catch_errors_setting, list) else []
    catch_errors_lower = [item.lower() for item in catch_errors] if catch_errors else []
    ignore_logs_list = ignore_logs_list_setting if isinstance(ignore_logs_list_setting, list) else []
    ignore_logs_list_lower = [item.lower() for item in ignore_logs_list] if ignore_logs_list else []
    ignore_logs_errors = ignore_logs_errors_setting if isinstance(ignore_logs_errors_setting, list) else []
    ignore_logs_errors_lower = [item.lower() for item in ignore_logs_errors] if ignore_logs_errors else []
    message_list: list[str] = []
    errors_list: list[str] = []

    valid_log_files = [file for file in folder_path.glob("*.log") if "crash-" not in file.name]
    for file in valid_log_files:
        if all(part not in str(file).lower() for part in ignore_logs_list_lower):
            try:
                with CMain.open_file_with_encoding(file) as log_file:
                    log_data = log_file.readlines()
                    log_data_lower = (line.lower() for line in log_data)
                    errors_list = [
                        f"ERROR > {line}"
                        for line in log_data_lower
                        if any(item in line for item in catch_errors_lower) and all(elem not in line for elem in ignore_logs_errors_lower)
                    ]

                if errors_list:
                    message_list.extend((
                        "[!] CAUTION : THE FOLLOWING LOG FILE REPORTS ONE OR MORE ERRORS!\n",
                        "[ Errors do not necessarily mean that the mod is not working. ]\n",
                        f"\nLOG PATH > {file}\n",
                        *errors_list,
                        f"\n* TOTAL NUMBER OF DETECTED LOG ERRORS * : {len(errors_list)}\n",
                    ))

            except OSError:
                message_list.append(f"❌ ERROR : Unable to scan this log file :\n  {file}")
                CMain.logger.warning(f"> ! > DETECT LOG ERRORS > UNABLE TO SCAN : {file}")
                continue

    return "".join(message_list)


# ================================================
# CHECK XSE PLUGINS FOLDER IN GAME DATA
# ================================================
def check_xse_plugins() -> str:  # RESERVED | Might be expanded upon in the future.
    message_list: list[str] = []
    plugins_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Game_Folder_Plugins")
    # TODO: Add NG version
    adlib_versions = {
        "VR Mode": ("version-1-2-72-0.csv", "Virtual Reality (VR) version", "https://www.nexusmods.com/fallout4/mods/64879?tab=files"),
        "Non-VR Mode": ("version-1-10-163-0.bin", "Non-VR (Regular) version", "https://www.nexusmods.com/fallout4/mods/47327?tab=files"),
    }

    if CMain.classic_settings(bool, "VR Mode"):
        selected_version = adlib_versions["VR Mode"]
        other_version = adlib_versions["Non-VR Mode"]
    else:
        selected_version = adlib_versions["Non-VR Mode"]
        other_version = adlib_versions["VR Mode"]

    if plugins_path and plugins_path.joinpath(selected_version[0]).exists():
        message_list.append("✔️ You have the latest version of the Address Library file!\n-----\n")
    elif plugins_path and plugins_path.joinpath(other_version[0]).exists():
        message_list.extend((
            "❌ CAUTION : You have installed the wrong version of the Address Library file!\n",
            f"  Remove the current Address Library file and install the {selected_version[1]}.\n",
            f"  Link: {selected_version[2]}\n-----\n",
        ))
    else:
        message_list.extend((
            "❓ NOTICE : Unable to locate Address Library\n",
            "  If you have Address Library installed, please check the path in your settings.\n",
            "  If you don't have it installed, you can find it on the Nexus.\n",
            f"  Link: {selected_version[2]}\n-----\n",
        ))

    return "".join(message_list)


# ================================================
# PAPYRUS MONITORING / LOGGING
# ================================================
def papyrus_logging() -> tuple[str, int]:
    message_list: list[str] = []
    papyrus_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Docs_File_PapyrusLog")

    count_dumps = count_stacks = count_warnings = count_errors = 0
    if papyrus_path and papyrus_path.exists():
        with papyrus_path.open("rb") as encode_test:
            papyrus_encoding = chardet.detect(encode_test.read())["encoding"]
        with papyrus_path.open(encoding=papyrus_encoding, errors="ignore") as papyrus_log:
            papyrus_data = papyrus_log.readlines()
        for line in papyrus_data:
            if "Dumping Stacks" in line:
                count_dumps += 1
            elif "Dumping Stack" in line:
                count_stacks += 1
            elif " warning: " in line:
                count_warnings += 1
            elif " error: " in line:
                count_errors += 1

        ratio = 0 if count_dumps == 0 else count_dumps / count_stacks

        message_list.extend((
            f"NUMBER OF DUMPS    : {count_dumps}\n",
            f"NUMBER OF STACKS   : {count_stacks}\n",
            f"DUMPS/STACKS RATIO : {round(ratio, 3)}\n",
            f"NUMBER OF WARNINGS : {count_warnings}\n",
            f"NUMBER OF ERRORS   : {count_errors}\n",
        ))
    else:
        message_list.extend((
            "[!] ERROR : UNABLE TO FIND *Papyrus.0.log* (LOGGING IS DISABLED OR YOU DIDN'T RUN THE GAME)\n",
            "ENABLE PAPYRUS LOGGING MANUALLY OR WITH BETHINI AND START THE GAME TO GENERATE THE LOG FILE\n",
            "BethINI Link | Use Manual Download : https://www.nexusmods.com/site/mods/631?tab=files\n",
        ))

    message_output = "".join(message_list)  # Debug print
    return message_output, count_dumps


# ================================================
# WRYE BASH - PLUGIN CHECKER
# ================================================
def scan_wryecheck() -> str:
    message_list: list[str] = []
    wrye_missinghtml_setting = CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_MODS.Warn_WRYE_MissingHTML")
    wrye_plugincheck = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Docs_File_WryeBashPC")
    wrye_warnings_setting = CMain.yaml_settings(dict[str, str], CMain.YAML.Main, "Warnings_WRYE")

    wrye_missinghtml = wrye_missinghtml_setting if isinstance(wrye_missinghtml_setting, str) else None
    wrye_warnings = wrye_warnings_setting if isinstance(wrye_warnings_setting, dict) else {}

    if wrye_plugincheck and wrye_plugincheck.is_file():
        message_list.extend((
            "\n✔️ WRYE BASH PLUGIN CHECKER REPORT WAS FOUND! ANALYZING CONTENTS...\n",
            f"  [This report is located in your Documents/My Games/{CMain.gamevars['game']} folder.]\n",
            "  [To hide this report, remove *ModChecker.html* from the same folder.]\n",
        ))
        with CMain.open_file_with_encoding(wrye_plugincheck) as WB_Check:
            WB_HTML = WB_Check.read()

        # Parse the HTML code using BeautifulSoup.
        soup = BeautifulSoup(WB_HTML, "html.parser")

        h3: PageElement
        for h3 in soup.find_all("h3"):  # Find all <h3> elems and loop through them.
            title = h3.get_text()  # Get title of current <h3> and create plugin list.
            plugin_list: list[str] = []

            for p in h3.find_next_siblings("p"):  # Find all <p> elements that come after current <h3> element.
                if p.find_previous_sibling("h3") == h3:  # Check if current <p> elem is under same <h3> elem as previous <p>.
                    text = p.get_text().strip().replace("•\xa0 ", "")
                    if any(ext in text for ext in (".esp", ".esl", ".esm")):  # Get text of <p> elem and check plugin extensions.
                        plugin_list.append(text)
                else:  # If current <p> elem is under a different <h3> elem, break loop.
                    break
            # Format title and list of plugins.
            if title != "Active Plugins:":
                if len(title) < 32:
                    diff = 32 - len(title)
                    left = diff // 2
                    right = diff - left
                    message_list.append(f"\n   {'=' * left} {title} {'=' * right}\n")
                else:
                    message_list.append(title)

            if title == "ESL Capable":
                message_list.extend((
                    f"❓ There are {len(plugin_list)} plugins that can be given the ESL flag. This can be done with\n",
                    "  the SimpleESLify script to avoid reaching the plugin limit (254 esm/esp).\n",
                    "  SimpleESLify: https://www.nexusmods.com/skyrimspecialedition/mods/27568\n  -----\n",
                ))

            message_list.extend([warn_desc for warn_name, warn_desc in wrye_warnings.items() if warn_name in title])

            if title not in {"ESL Capable", "Active Plugins:"}:
                message_list.extend([f"    > {elem}\n" for elem in plugin_list])

        message_list.extend((
            "\n❔ For more info about the above detected problems, see the WB Advanced Readme\n",
            "  For more details about solutions, read the Advanced Troubleshooting Article\n",
            "  Advanced Troubleshooting: https://www.nexusmods.com/fallout4/articles/4141\n",
            "  Wrye Bash Advanced Readme Documentation: https://wrye-bash.github.io/docs/\n",
            "  [ After resolving any problems, run Plugin Checker in Wrye Bash again! ]\n\n",
        ))
    elif wrye_missinghtml is not None:
        message_list.append(wrye_missinghtml)
    else:
        raise ValueError("ERROR: Warnings_WRYE missing from the database!")

    return "".join(message_list)


# ================================================
# CHECK MOD INI FILES
# ================================================
def scan_mod_inis() -> str:
    """Check INI files for mods."""
    message_list: list[str] = []
    vsync_list: list[str] = []

    config_files = ConfigFileCache()
    # TODO: Maybe return a message that no ini files were found? (See also: TODO in ConfigFileCache)
    # if not config_files:
    #     pass

    game_lower = CMain.gamevars["game"].lower()

    for file_lower, file_path in config_files.items():
        if file_lower.startswith(game_lower) and config_files.has(file_lower, "General", "sStartingConsoleCommand"):
            message_list.extend((
                f"[!] NOTICE: {file_path} contains the *sStartingConsoleCommand* setting.\n",
                "In rare cases, this setting can slow down the initial game startup time for some players.\n",
                "You can test your initial startup time difference by removing this setting from the INI file.\n-----\n",
            ))

    # TODO: Support for other exe file names
    if config_files.get(bool, "dxvk.conf", f"{CMain.gamevars['game']}.exe", "dxgi.syncInterval"):
        vsync_list.append(f"{config_files['dxvk.conf']} | SETTING: dxgi.syncInterval\n")
    if config_files.get(bool, "enblocal.ini", "ENGINE", "ForceVSync"):
        vsync_list.append(f"{config_files['enblocal.ini']} | SETTING: ForceVSync\n")
    if config_files.get(bool, "longloadingtimesfix.ini", "Limiter", "EnableVSync"):
        vsync_list.append(f"{config_files['longloadingtimesfix.ini']} | SETTING: EnableVSync\n")
    if config_files.get(bool, "reshade.ini", "APP", "ForceVsync"):
        vsync_list.append(f"{config_files['reshade.ini']} | SETTING: ForceVsync\n")
    if config_files.get(bool, "fallout4_test.ini", "CreationKit", "VSyncRender"):
        vsync_list.append(f"{config_files['fallout4_test.ini']} | SETTING: VSyncRender\n")

    if "; F10" in config_files.get_strict(str, "espexplorer.ini", "General", "HotKey"):
        config_files.set(str, "espexplorer.ini", "General", "HotKey", "0x79")
        CMain.logger.info(f"> > > PERFORMED INI HOTKEY FIX FOR {config_files['espexplorer.ini']}")
        message_list.append(f"> Performed INI Hotkey Fix For : {config_files['espexplorer.ini']}\n")

    if config_files.get_strict(int, "epo.ini", "Particles", "iMaxDesired") > 5000:
        config_files.set(int, "epo.ini", "Particles", "iMaxDesired", 5000)
        CMain.logger.info(f"> > > PERFORMED INI PARTICLE COUNT FIX FOR {config_files['epo.ini']}")
        message_list.append(f"> Performed INI Particle Count Fix For : {config_files['epo.ini']}\n")

    if "f4ee.ini" in config_files:
        if config_files.get(int, "f4ee.ini", "CharGen", "bUnlockHeadParts") == 0:
            config_files.set(int, "f4ee.ini", "CharGen", "bUnlockHeadParts", 1)
            CMain.logger.info(f"> > > PERFORMED INI HEAD PARTS UNLOCK FOR {config_files['f4ee.ini']}")
            message_list.append(f"> Performed INI Head Parts Unlock For : {config_files['f4ee.ini']}\n")

        if config_files.get(int, "f4ee.ini", "CharGen", "bUnlockTints") == 0:
            config_files.set(int, "f4ee.ini", "CharGen", "bUnlockTints", 1)
            CMain.logger.info(f"> > > PERFORMED INI FACE TINTS UNLOCK FOR {config_files['f4ee.ini']}")
            message_list.append(f"> Performed INI Face Tints Unlock For : {config_files['f4ee.ini']}\n")

    if "highfpsphysicsfix.ini" in config_files:
        if config_files.get(bool, "highfpsphysicsfix.ini", "Main", "EnableVSync"):
            vsync_list.append(f"{config_files['highfpsphysicsfix.ini']} | SETTING: EnableVSync\n")

        if config_files.get_strict(float, "highfpsphysicsfix.ini", "Limiter", "LoadingScreenFPS") < 600.0:
            config_files.set(float, "highfpsphysicsfix.ini", "Limiter", "LoadingScreenFPS", 600.0)
            CMain.logger.info(f"> > > PERFORMED INI LOADING SCREEN FPS FIX FOR {config_files['highfpsphysicsfix.ini']}")
            message_list.append(f"> Performed INI Loading Screen FPS Fix For : {config_files['highfpsphysicsfix.ini']}\n")

    if vsync_list:
        message_list.extend((
            "* NOTICE : VSYNC IS CURRENTLY ENABLED IN THE FOLLOWING FILES *\n",
            *vsync_list,
        ))

    if config_files.duplicate_files:
        all_duplicates: list[Path] = []
        for paths in config_files.duplicate_files.values():
            all_duplicates.extend(paths)
        all_duplicates.extend([fp for f, fp in config_files.items() if f in config_files.duplicate_files])
        message_list.extend((
            "* NOTICE : DUPLICATES FOUND OF THE FOLLOWING FILES *\n",
            *[str(p) for p in sorted(all_duplicates, key=lambda p: p.name)],
        ))
    return "".join(message_list)


# ================================================
# CHECK ALL UNPACKED / LOOSE MOD FILES
# ================================================
def scan_mods_unpacked() -> str:
    message_list: list[str] = [
        "=================== MOD FILES SCAN ====================\n",
        "========= RESULTS FROM UNPACKED / LOOSE FILES =========\n",
    ]
    cleanup_list: set[str] = set()
    animdata_list: set[str] = set()
    tex_dims_list: set[str] = set()
    tex_frmt_list: set[str] = set()
    snd_frmt_list: set[str] = set()
    xse_file_list: set[str] = set()
    previs_list: set[str] = set()
    xse_acronym_setting = CMain.yaml_settings(str, CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.XSE_Acronym")
    xse_scriptfiles_setting = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.XSE_HashedScripts")

    xse_acronym = xse_acronym_setting if isinstance(xse_acronym_setting, str) else "XSE"
    xse_scriptfiles = xse_scriptfiles_setting if isinstance(xse_scriptfiles_setting, dict) else {}

    backup_path = Path("CLASSIC Backup/Cleaned Files")
    if not TEST_MODE:
        backup_path.mkdir(parents=True, exist_ok=True)

    mod_path = CMain.classic_settings(Path, "MODS Folder Path")
    if not mod_path:
        return str(CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Path_Missing"))

    if not mod_path.is_dir():
        return str(CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Path_Invalid"))

    print("✔️ MODS FOLDER PATH FOUND! PERFORMING INITIAL MOD FILES CLEANUP...")

    filter_names = ("readme", "changes", "changelog", "change log")
    for root, dirs, files in mod_path.walk(top_down=False):
        root_main = root.relative_to(mod_path).parent
        has_anim_data = False
        for dirname in dirs:
            dirname_lower = dirname.lower()
            # ================================================
            # DETECT MODS WITH AnimationFileData
            if not has_anim_data and dirname_lower == "animationfiledata":
                has_anim_data = True
                animdata_list.add(f"  - {root_main}\n")
            # ================================================
            # (RE)MOVE REDUNDANT FOMOD FOLDERS
            elif dirname_lower == "fomod":
                fomod_folder_path = root / dirname
                relative_path = fomod_folder_path.relative_to(mod_path)
                new_folder_path = backup_path / relative_path

                if not TEST_MODE:
                    shutil.move(fomod_folder_path, new_folder_path)
                cleanup_list.add(f"  - {relative_path}\n")

        for filename in files:
            filename_lower = filename.lower()
            # ================================================
            # (RE)MOVE REDUNDANT README / CHANGELOG FILES
            if filename_lower.endswith(".txt") and any(name in filename_lower for name in filter_names):
                file_path = root / filename
                relative_path = file_path.relative_to(mod_path)
                new_file_path = backup_path / relative_path
                if not TEST_MODE:
                    new_file_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(file_path, new_file_path)
                cleanup_list.add(f"  - {relative_path}\n")

    print("✔️ CLEANUP COMPLETE! NOW ANALYZING ALL UNPACKED/LOOSE MOD FILES...")

    for root, _, files in mod_path.walk(top_down=False):
        root_main = root.relative_to(mod_path).parent

        has_previs_files = False
        has_xse_files = False
        for filename in files:
            filename_lower = filename.lower()
            file_path = root / filename
            relative_path = file_path.relative_to(mod_path)
            file_ext = file_path.suffix.lower()
            # ================================================
            # DETECT DDS FILES WITH INCORRECT DIMENSIONS
            if file_ext == ".dds":
                with file_path.open("rb") as dds_file:
                    dds_data = dds_file.read(20)
                if dds_data[:4] == b"DDS ":
                    # TODO: Warn if magic bytes differ
                    width = struct.unpack("<I", dds_data[12:16])[0]
                    height = struct.unpack("<I", dds_data[16:20])[0]
                    if width % 2 != 0 or height % 2 != 0:
                        tex_dims_list.add(f"  - {relative_path} ({width}x{height})")
            # ================================================
            # DETECT INVALID TEXTURE FILE FORMATS
            elif file_ext in {".tga", ".png"} and "BodySlide" not in file_path.parts:
                tex_frmt_list.add(f"  - {file_ext[1:].upper()} : {relative_path}\n")
            # ================================================
            # DETECT INVALID SOUND FILE FORMATS
            elif file_ext in {".mp3", ".m4a"}:
                snd_frmt_list.add(f"  - {file_ext[1:].upper()} : {relative_path}\n")
            # ================================================
            # DETECT MODS WITH SCRIPT EXTENDER FILE COPIES
            elif (
                not has_xse_files
                and any(filename_lower == key.lower() for key in xse_scriptfiles)
                and "workshop framework" not in str(root).lower()
                and f"Scripts\\{filename}" in str(file_path)
            ):
                has_xse_files = True
                xse_file_list.add(f"  - {root_main}\n")
            # ================================================
            # DETECT MODS WITH PRECOMBINE / PREVIS FILES
            elif not has_previs_files and filename_lower.endswith((".uvd", "_oc.nif")):
                has_previs_files = True
                previs_list.add(f"  - {root_main}\n")

    if xse_file_list:
        message_list.extend([
            f"\n# ⚠️ FOLDERS CONTAIN COPIES OF *{xse_acronym}* SCRIPT FILES ⚠️\n",
            "▶️ Any mods with copies of original Script Extender files\n",
            "  may cause script related problems or crashes.\n\n",
            *sorted(xse_file_list),
        ])
    if previs_list:
        message_list.extend([
            "\n# ⚠️ FOLDERS CONTAIN LOOSE PRECOMBINE / PREVIS FILES ⚠️\n",
            "▶️ Any mods that contain custom precombine/previs files\n",
            "  should load after the PRP.esp plugin from Previs Repair Pack (PRP).\n",
            "  Otherwise, see if there is a PRP patch available for these mods.\n\n",
            *sorted(previs_list),
        ])
    if tex_dims_list:
        message_list.extend([
            "\n# ⚠️ DDS DIMENSIONS ARE NOT DIVISIBLE BY 2 ⚠️\n",
            "▶️ Any mods that have texture files with incorrect dimensions\n",
            "  are very likely to cause a *Texture (DDS) Crash*. For further details,\n",
            "  read the *How To Read Crash Logs.pdf* included with the CLASSIC exe.\n\n",
            *sorted(tex_dims_list),
        ])
    if tex_frmt_list:
        message_list.extend([
            "\n# ❓ TEXTURE FILES HAVE INCORRECT FORMAT, SHOULD BE DDS ❓\n",
            "▶️ Any files with an incorrect file format will not work.\n",
            "  Mod authors should convert these files to their proper game format.\n",
            "  If possible, notify the original mod authors about these problems.\n\n",
            *sorted(tex_frmt_list),
        ])
    if snd_frmt_list:
        message_list.extend([
            "\n# ❓ SOUND FILES HAVE INCORRECT FORMAT, SHOULD BE XWM OR WAV ❓\n",
            "▶️ Any files with an incorrect file format will not work.\n",
            "  Mod authors should convert these files to their proper game format.\n",
            "  If possible, notify the original mod authors about these problems.\n\n",
            *sorted(snd_frmt_list),
        ])
    if animdata_list:
        message_list.extend([
            "\n# ❓ FOLDERS CONTAIN CUSTOM ANIMATION FILE DATA ❓\n",
            "▶️ Any mods that have their own custom Animation File Data\n",
            "  may rarely cause an *Animation Corruption Crash*. For further details,\n",
            "  read the *How To Read Crash Logs.pdf* included with the CLASSIC exe.\n\n",
            *sorted(animdata_list),
        ])
    if cleanup_list:
        message_list.extend([
            "\n# 📄 DOCUMENTATION FILES MOVED TO 'CLASSIC Backup\\Cleaned Files' 📄\n",
            *sorted(cleanup_list),
        ])

    return "".join(message_list)


# ================================================
# CHECK ALL ARCHIVED / BA2 MOD FILES
# ================================================
def scan_mods_archived() -> str:
    message_list: list[str] = [
        "\n========== RESULTS FROM ARCHIVED / BA2 FILES ==========\n",
    ]
    ba2_frmt_list: set[str] = set()
    animdata_list: set[str] = set()
    tex_dims_list: set[str] = set()
    tex_frmt_list: set[str] = set()
    snd_frmt_list: set[str] = set()
    xse_file_list: set[str] = set()
    previs_list: set[str] = set()

    xse_acronym_setting = CMain.yaml_settings(str, CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.XSE_Acronym")
    xse_scriptfiles_setting = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.XSE_HashedScripts")

    xse_acronym = xse_acronym_setting if isinstance(xse_acronym_setting, str) else ""
    xse_scriptfiles = xse_scriptfiles_setting if isinstance(xse_scriptfiles_setting, dict) else {}

    bsarch_path = Path.cwd() / "CLASSIC Data/BSArch.exe"
    mod_path = CMain.classic_settings(Path, "MODS Folder Path")
    if not mod_path:
        return str(CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Path_Missing"))

    if not mod_path.exists():
        return str(CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Path_Invalid"))

    if not bsarch_path.exists():
        return str(CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_BSArch_Missing"))

    print("✔️ ALL REQUIREMENTS SATISFIED! NOW ANALYZING ALL BA2 MOD ARCHIVES...")

    for root, _, files in mod_path.walk(top_down=False):
        for filename in files:
            filename_lower = filename.lower()
            if not filename_lower.endswith(".ba2") or filename_lower == "prp - main.ba2":
                continue
            file_path = root / filename

            try:
                with file_path.open("rb") as f:
                    header = f.read(12)
            except OSError:
                print("Failed to read file:", filename)
                continue

            if header[:4] != b"BTDX" or header[8:] not in {b"DX10", b"GNRL"}:
                ba2_frmt_list.add(f"  - {filename} : {header!s}\n")
                continue

            if header[8:] == b"DX10":
                # Texture-format BA2
                command_dump = (bsarch_path, file_path, "-dump")
                archive_dump = subprocess.run(command_dump, shell=True, capture_output=True, text=True, check=False)
                if archive_dump.returncode != 0:
                    print("BSArch command failed:", archive_dump.returncode, archive_dump.stderr)
                    continue

                output_split = archive_dump.stdout.split("\n\n")
                error_check = output_split[-1]
                if error_check.startswith("Error:"):
                    print("BSArch command failed:", error_check, archive_dump.stderr)
                    continue

                for file_block in output_split[4:]:
                    if not file_block:
                        continue

                    block_split = file_block.split("\n", 3)
                    # Textures\Props\NukaColaQuantum_d.DDS
                    #   DirHash: E10CD7B7  NameHash: ECE5A99C  Ext: dds
                    #   Width:  512  Height:  512  CubeMap: No  Format: DXGI_FORMAT_BC1_UNORM

                    # ================================================
                    # DETECT INVALID TEXTURE FILE FORMATS
                    if "Ext: dds" not in block_split[1]:
                        tex_frmt_list.add(f"  - {block_split[0].rsplit('.', 1)[-1].upper()} : {filename} > {block_split[0]}\n")
                        continue

                    # ================================================
                    # DETECT DDS FILES WITH INCORRECT DIMENSIONS
                    _, width, _, height, _ = block_split[2].split(maxsplit=4)
                    if (width.isdecimal() and int(width) % 2 != 0) or (height.isdecimal() and int(height) % 2 != 0):
                        tex_dims_list.add(f"  - {width}x{height} : {filename} > {block_split[0]}")

            else:
                # General-format BA2
                command_list = (bsarch_path, file_path, "-list")
                archive_list = subprocess.run(command_list, shell=True, capture_output=True, text=True, check=False)
                if archive_list.returncode != 0:
                    print("BSArch command failed:", archive_list.returncode, archive_list.stderr)
                    continue

                output_split = archive_list.stdout.lower().split("\n")
                # Output is a simple list of file paths
                # Textures\Props\NukaColaQuantum_d.DDS

                has_previs_files = False
                has_anim_data = False
                has_xse_files = False
                for file in output_split[15:]:
                    # ================================================
                    # DETECT INVALID SOUND FILE FORMATS
                    if file.endswith((".mp3", ".m4a")):
                        snd_frmt_list.add(f"  - {file[-3:].upper()} : {filename} > {file}\n")
                    # ================================================
                    # DETECT MODS WITH AnimationFileData
                    elif not has_anim_data and "animationfiledata" in file:
                        has_anim_data = True
                        animdata_list.add(f"  - {filename}\n")
                    # ================================================
                    # DETECT MODS WITH SCRIPT EXTENDER FILE COPIES
                    elif (
                        not has_xse_files
                        and any(f"scripts\\{key.lower()}" in file for key in xse_scriptfiles)
                        and "workshop framework" not in str(root).lower()
                    ):
                        has_xse_files = True
                        xse_file_list.add(f"  - {filename}\n")
                    # ================================================
                    # DETECT MODS WITH PRECOMBINE / PREVIS FILES
                    elif not has_previs_files and file.endswith((".uvd", "_oc.nif")):
                        has_previs_files = True
                        previs_list.add(f"  - {filename}\n")

    if xse_file_list:
        message_list.extend([
            f"\n# ⚠️ BA2 ARCHIVES CONTAIN COPIES OF *{xse_acronym}* SCRIPT FILES ⚠️\n",
            "▶️ Any mods with copies of original Script Extender files\n",
            "  may cause script related problems or crashes.\n\n",
            *sorted(xse_file_list),
        ])
    if previs_list:
        message_list.extend([
            "\n# ⚠️ BA2 ARCHIVES CONTAIN CUSTOM PRECOMBINE / PREVIS FILES ⚠️\n",
            "▶️ Any mods that contain custom precombine/previs files\n",
            "  should load after the PRP.esp plugin from Previs Repair Pack (PRP).\n",
            "  Otherwise, see if there is a PRP patch available for these mods.\n\n",
            *sorted(previs_list),
        ])
    if tex_dims_list:
        message_list.extend([
            "\n# ⚠️ DDS DIMENSIONS ARE NOT DIVISIBLE BY 2 ⚠️\n",
            "▶️ Any mods that have texture files with incorrect dimensions\n",
            "  are very likely to cause a *Texture (DDS) Crash*. For further details,\n",
            "  read the *How To Read Crash Logs.pdf* included with the CLASSIC exe.\n\n",
            *sorted(tex_dims_list),
        ])
    if tex_frmt_list:
        message_list.extend([
            "\n# ❓ TEXTURE FILES HAVE INCORRECT FORMAT, SHOULD BE DDS ❓\n",
            "▶️ Any files with an incorrect file format will not work.\n",
            "  Mod authors should convert these files to their proper game format.\n",
            "  If possible, notify the original mod authors about these problems.\n\n",
            *sorted(tex_frmt_list),
        ])
    if snd_frmt_list:
        message_list.extend([
            "\n# ❓ SOUND FILES HAVE INCORRECT FORMAT, SHOULD BE XWM OR WAV ❓\n",
            "▶️ Any files with an incorrect file format will not work.\n",
            "  Mod authors should convert these files to their proper game format.\n",
            "  If possible, notify the original mod authors about these problems.\n\n",
            *sorted(snd_frmt_list),
        ])
    if animdata_list:
        message_list.extend([
            "\n# ❓ BA2 ARCHIVES CONTAIN CUSTOM ANIMATION FILE DATA ❓\n",
            "▶️ Any mods that have their own custom Animation File Data\n",
            "  may rarely cause an *Animation Corruption Crash*. For further details,\n",
            "  read the *How To Read Crash Logs.pdf* included with the CLASSIC exe.\n\n",
            *sorted(animdata_list),
        ])
    if ba2_frmt_list:
        message_list.extend([
            "\n# ❓ BA2 ARCHIVES HAVE INCORRECT FORMAT, SHOULD BE BTDX-GNRL OR BTDX-DX10 ❓\n",
            "▶️ Any files with an incorrect file format will not work.\n",
            "  Mod authors should convert these files to their proper game format.\n",
            "  If possible, notify the original mod authors about these problems.\n\n",
            *sorted(ba2_frmt_list),
        ])

    return "".join(message_list)


# ================================================
# BACKUP / RESTORE / REMOVE
# ================================================
def game_files_manage(classic_list: str, mode: Literal["BACKUP", "RESTORE", "REMOVE"] = "BACKUP") -> None:
    game_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Root_Folder_Game")
    manage_list_setting = CMain.yaml_settings(list[str], CMain.YAML.Game, classic_list)
    manage_list = manage_list_setting if isinstance(manage_list_setting, list) else []

    if game_path is None or not game_path.is_dir():
        raise FileNotFoundError

    backup_path = Path(f"CLASSIC Backup/Game Files/{classic_list}")
    backup_path.mkdir(parents=True, exist_ok=True)
    list_name = classic_list.split(maxsplit=1)[-1]

    if mode == "BACKUP":
        print(f"CREATING A BACKUP OF {list_name} FILES, PLEASE WAIT...")
        try:
            for file in game_path.glob("*"):
                if any(item.lower() in file.name.lower() for item in manage_list):
                    destination_file = backup_path / file.name
                    if file.is_file():
                        shutil.copy2(file, destination_file)
                    elif file.is_dir():
                        if destination_file.is_dir():
                            shutil.rmtree(destination_file)
                        elif destination_file.is_file():
                            destination_file.unlink(missing_ok=True)
                        shutil.copytree(file, destination_file)
            print(f"✔️ SUCCESSFULLY CREATED A BACKUP OF {list_name} FILES\n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO BACKUP {list_name} FILES DUE TO FILE PERMISSIONS!")
            print("    TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")

    elif mode == "RESTORE":
        print(f"RESTORING {list_name} FILES FROM A BACKUP, PLEASE WAIT...")
        try:
            for file in game_path.glob("*"):
                if any(item.lower() in file.name.lower() for item in manage_list):
                    destination_file = backup_path / file.name
                    if destination_file.is_file():
                        shutil.copy2(destination_file, file)
                    elif destination_file.is_dir():
                        if file.is_dir():
                            shutil.rmtree(file)
                        elif file.exists():
                            file.unlink(missing_ok=True)
                        shutil.copytree(destination_file, file)
            print(f"✔️ SUCCESSFULLY RESTORED {list_name} FILES TO THE GAME FOLDER\n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO RESTORE {list_name} FILES DUE TO FILE PERMISSIONS!")
            print("    TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")

    elif mode == "REMOVE":
        print(f"REMOVING {list_name} FILES FROM YOUR GAME FOLDER, PLEASE WAIT...")
        try:
            for file in game_path.glob("*"):
                if any(item.lower() in file.name.lower() for item in manage_list):
                    if file.is_file():
                        file.unlink(missing_ok=True)
                    elif file.is_dir():
                        os.removedirs(file)
            print(f"✔️ SUCCESSFULLY REMOVED {list_name} FILES FROM THE GAME FOLDER\n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO REMOVE {list_name} FILES DUE TO FILE PERMISSIONS!")
            print("  TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")


# ================================================
# COMBINED RESULTS
# ================================================
def game_combined_result() -> str:
    docs_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Root_Folder_Docs")
    game_path = CMain.yaml_settings(Path, CMain.YAML.Game_Local, f"Game{CMain.gamevars['vr']}_Info.Root_Folder_Game")

    if not (game_path and docs_path):
        return ""
    return "".join((
        check_xse_plugins(),
        check_crashgen_settings(),
        check_log_errors(docs_path),
        check_log_errors(game_path),
        scan_wryecheck(),
        scan_mod_inis(),
    ))


def mods_combined_result() -> str:  # KEEP THESE SEPARATE SO THEY ARE NOT INCLUDED IN AUTOSCAN REPORTS
    unpacked = scan_mods_unpacked()
    if unpacked.startswith("❌ MODS FOLDER PATH NOT PROVIDED"):
        return unpacked
    return unpacked + scan_mods_archived()


def write_combined_results() -> None:
    game_result = game_combined_result()
    mods_result = mods_combined_result()
    gfs_report = Path("CLASSIC GFS Report.md")
    with gfs_report.open("w", encoding="utf-8", errors="ignore") as scan_report:
        scan_report.write(game_result + mods_result)


if __name__ == "__main__":
    CMain.initialize()
    CMain.main_generate_required()
    if TEST_MODE:
        write_combined_results()
    else:
        print(game_combined_result())
        print(mods_combined_result())
        game_files_manage("Backup ENB")
        os.system("pause")
