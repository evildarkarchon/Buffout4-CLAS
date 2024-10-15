import functools
import os
import shutil
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import chardet
import iniparse  # type: ignore
import tomlkit
from bs4 import BeautifulSoup, PageElement

import CLASSIC_Main as CMain


# ================================================
# DEFINE MAIN FILE / YAML FUNCTIONS
# ================================================
def handle_ini_exceptions(func: Callable) -> Callable:
    @functools.wraps(func)
    def wrapper(*args: tuple[Any], **kwargs: dict[Any, Any]) -> Any | None:
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            CMain.logger.error(f"ERROR: File not found - {e}")
        except KeyError as e:
            CMain.logger.error(f"ERROR: Invalid section or key - {e}")
        except OSError as e:
            CMain.logger.error(f"ERROR: Unable to read or write the file - {e}")
        except UnicodeError as e:
            CMain.logger.error(f"ERROR: Unable to read the file due to encoding issues - {e}")
        except Exception as e:  # noqa: BLE001
            CMain.logger.error(f"ERROR: An unexpected error occurred - {e}")
        return None
    return wrapper

@handle_ini_exceptions
def mod_ini_config(ini_path: Path | str, section: str, key: str, new_value: str | None = None) -> str | bool:
    ini_path = Path(ini_path)
    with ini_path.open("rb") as config_file:
        ini_encoding = chardet.detect(config_file.read())["encoding"]

    config = iniparse.ConfigParser()
    with ini_path.open(encoding=ini_encoding) as config_file:
        config.readfp(config_file)

    if not config.has_section(section):
        raise KeyError(f"Section '{section}' does not exist in '{ini_path}'")
    if not config.has_option(section, key):
        raise KeyError(f"Key '{key}' does not exist in section '{section}'")

    # If new_value is specified, update value in INI.
    if new_value is not None:
        config.set(section, key, str(new_value))
        with ini_path.open("w", encoding=ini_encoding) as config_file:
            config.write(config_file)
        return new_value

    value = config.get(section, key)
    if value.lower() in {"1", "true", "0", "false"}:
        return config.getboolean(section, key)

    return value


def mod_toml_config(toml_path: Path, section: str, key: str, new_value: str | None = None) -> Any | None:
    """Read the TOML file"""
    with CMain.open_file_with_encoding(toml_path) as toml_file:
        data = tomlkit.parse(toml_file.read())

    if section not in data or key in data[section]: # type: ignore
        return None
    current_value = data[section][key] # type: ignore

    # If a new value is provided, update the key
    if new_value is not None:
        data[section][key] = new_value # type: ignore
        with toml_path.open("w") as toml_file:
            toml_file.write(data.as_string())
    return current_value


# ================================================
# CHECK BUFFOUT CONFIG SETTINGS
# ================================================
def check_crashgen_settings() -> str:
    message_list: list[str] = []
    plugins_folder = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Game_Folder_Plugins")
    crashgen_name_setting = CMain.yaml_settings(CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.CRASHGEN_LogName")
    xse_folder = CMain.yaml_settings(CMain.YAML.Game_Local, "Game_Info.Docs_Folder_XSE")

    plugins_path = Path(plugins_folder) if isinstance(plugins_folder, str) else None
    crashgen_name = crashgen_name_setting if isinstance(crashgen_name_setting, str) else ""
    xse_path = Path(xse_folder) if isinstance(xse_folder, str) else None

    crashgen_toml_og = plugins_path / "Buffout4/config.toml" if plugins_path else None
    crashgen_toml_vr = plugins_path / "Buffout4.toml" if plugins_path else None
    if crashgen_toml_og and crashgen_toml_og.is_file():
        crashgen_toml_main = crashgen_toml_og
    elif crashgen_toml_vr and crashgen_toml_vr.is_file():
        crashgen_toml_main = crashgen_toml_vr
    else:
        raise FileNotFoundError("Buffout4.toml not found in the plugins folder.")

    if (crashgen_toml_og and crashgen_toml_og.is_file()) and (crashgen_toml_vr and crashgen_toml_vr.is_file()):
        message_list.extend([f"# ❌ CAUTION : BOTH VERSIONS OF {crashgen_name.upper()} TOML SETTINGS FILES WERE FOUND! #\n",
                             f"When editing {crashgen_name} toml settings, make sure you are editing the correct file. \n",
                             f"Please recheck your {crashgen_name} installation and delete any obsolete files. \n-----\n"])

    xse_files = {file.name.lower() for file in xse_path.iterdir()} if xse_path else set()
    Has_XCell = any("x-cell" in file for file in xse_files)
    Has_BakaScrapHeap = any("bakascrapheap" in file for file in xse_files)
    if crashgen_toml_main:
        if xse_files and mod_toml_config(crashgen_toml_main, "Patches", "Achievements") and any("achievements" in file for file in xse_files):
            message_list.extend(["# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE # \n",
                                 f"    Auto Scanner will change this parameter to FALSE to prevent conflicts with {crashgen_name}. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "Achievements", "False")
        else:
            message_list.append(f"✔️ Achievements parameter is correctly configured in your {crashgen_name} settings! \n-----\n")

        if Has_BakaScrapHeap and mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager"):
            message_list.extend(["# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but MemoryManager parameter is set to TRUE # \n",
                                 f"    Auto Scanner will change this parameter to FALSE to prevent conflicts with {crashgen_name}. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager", "False")
        elif Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager"):
            message_list.extend(["# ❌ CAUTION : The X-Cell Mod is installed, but MemoryManager parameter is set to TRUE # \n",
                                 "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "MemoryManager", "False")
        else:
            message_list.append(f"✔️ Memory Manager parameter is correctly configured in your {crashgen_name} settings! \n-----\n")

        if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "HavokMemorySystem"):
            message_list.extend(["# ❌ CAUTION : The X-Cell Mod is installed, but HavokMemorySystem parameter is set to TRUE # \n",
                                 "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "HavokMemorySystem", "False")
        else:
            message_list.append(f"✔️ HavokMemorySystem parameter is correctly configured in your {crashgen_name} settings! \n-----\n")

        if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "BSTextureStreamerLocalHeap"):
            message_list.extend(["# ❌ CAUTION : The X-Cell Mod is installed, but BSTextureStreamerLocalHeap parameter is set to TRUE # \n",
                                 "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "BSTextureStreamerLocalHeap", "False")
        else:
            message_list.append(f"✔️ BSTextureStreamerLocalHeap parameter is correctly configured in your {crashgen_name} settings! \n-----\n")

        if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "ScaleformAllocator"):
            message_list.extend(["# ❌ CAUTION : The X-Cell Mod is installed, but ScaleformAllocator parameter is set to TRUE # \n",
                                 "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "ScaleFormAllocator", "False")
        else:
            message_list.append(f"✔️ ScaleformAllocator parameter is correctly configured in your {crashgen_name} settings! \n-----\n")

        if Has_XCell and mod_toml_config(crashgen_toml_main, "Patches", "SmallBlockAllocator"):
            message_list.extend(["# ❌ CAUTION : The X-Cell Mod is installed, but SmallBlockAllocator parameter is set to TRUE # \n",
                                 "    Auto Scanner will change this parameter to FALSE to prevent conflicts with X-Cell. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Patches", "SmallBlockAllocator", "False")
        else:
            message_list.append(f"✔️ SmallBlockAllocator parameter is correctly configured in your {crashgen_name} settings! \n-----\n")


        if xse_files and mod_toml_config(crashgen_toml_main, "Compatibility", "F4EE") and any("f4ee" in file for file in xse_files):
            message_list.extend(["# ❌ CAUTION : Looks Menu is installed, but F4EE parameter under [Compatibility] is set to FALSE # \n",
                                 "    Auto Scanner will change this parameter to TRUE to prevent bugs and crashes from Looks Menu. \n-----\n"])
            mod_toml_config(crashgen_toml_main, "Compatibility", "F4EE", "True")
        else:
            message_list.append(f"✔️ F4EE (Looks Menu) parameter is correctly configured in your {crashgen_name} settings! \n-----\n")
    else:
        message_list.extend([f"# [!] NOTICE : Unable to find the {crashgen_name} config file, settings check will be skipped. # \n",
                             f"  To ensure this check doesn't get skipped, {crashgen_name} has to be installed manually. \n",
                             "  [ If you are using Mod Organizer 2, you need to run CLASSIC through a shortcut in MO2. ] \n-----\n"])

    return "".join(message_list)


# ================================================
# CHECK ERRORS IN LOG FILES FOR GIVEN FOLDER
# ================================================
def check_log_errors(folder_path: Path | str) -> str:
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)
    catch_errors_setting = CMain.yaml_settings(CMain.YAML.Main, "catch_log_errors")
    ignore_logs_list_setting = CMain.yaml_settings(CMain.YAML.Main, "exclude_log_files")
    ignore_logs_errors_setting = CMain.yaml_settings(CMain.YAML.Main, "exclude_log_errors")

    catch_errors = catch_errors_setting if isinstance(catch_errors_setting, list) else []
    ignore_logs_list = ignore_logs_list_setting if isinstance(ignore_logs_list_setting, list) else []
    ignore_logs_errors = ignore_logs_errors_setting if isinstance(ignore_logs_errors_setting, list) else []
    message_list: list[str] = []
    errors_list: list[str] = []

    valid_log_files = [file for file in folder_path.glob("*.log") if "crash-" not in file.name]
    for file in valid_log_files:
        if all(part.lower() not in str(file).lower() for part in ignore_logs_list):
            try:
                with CMain.open_file_with_encoding(file) as log_file:
                    log_data = log_file.readlines()
                for line in log_data:
                    line_lower = line.lower()
                    if any(item.lower() in line_lower for item in catch_errors) and all(elem.lower() not in line_lower for elem in ignore_logs_errors):
                        errors_list.append(f"ERROR > {line}")

                if errors_list:
                    message_list.extend(["[!] CAUTION : THE FOLLOWING LOG FILE REPORTS ONE OR MORE ERRORS! \n",
                                         "[ Errors do not necessarily mean that the mod is not working. ] \n",
                                         f"\nLOG PATH > {file} \n"])
                    message_list.extend(errors_list)

                    message_list.append(f"\n* TOTAL NUMBER OF DETECTED LOG ERRORS * : {len(errors_list)} \n")

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
    plugins_folder = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Game_Folder_Plugins")
    plugins_path = Path(plugins_folder) if isinstance(plugins_folder, str) and len(plugins_folder) >= 1  else None
    adlib_versions = {"VR Mode": ("version-1-2-72-0.csv", "Virtual Reality (VR) version", "https://www.nexusmods.com/fallout4/mods/64879?tab=files"),
                      "Non-VR Mode": ("version-1-10-163-0.bin", "Non-VR (Regular) version", "https://www.nexusmods.com/fallout4/mods/47327?tab=files")}

    enabled_mode = "VR Mode" if CMain.classic_settings("VR Mode") else "Non-VR Mode"
    selected_version = adlib_versions[enabled_mode]
    other_version = adlib_versions["VR Mode" if enabled_mode == "Non-VR Mode" else "Non-VR Mode"]

    if plugins_path and plugins_path.joinpath(selected_version[0]).exists():
        message_list.append("✔️ You have the latest version of the Address Library file! \n-----\n")
    elif plugins_path and plugins_path.joinpath(other_version[0]).exists():
        message_list.extend(["❌ CAUTION : You have installed the wrong version of the Address Library file! \n",
                             f"  Remove the current Address Library file and install the {selected_version[1]}.\n",
                             f"  Link: {selected_version[2]} \n-----\n"])
    else:
        message_list.extend(["❓ NOTICE : Unable to locate Address Library \n",
                             "  If you have Address Library installed, please check the path in your settings. \n",
                             "  If you don't have it installed, you can find it on the Nexus. \n",
                             f"  Link: {selected_version[2]} \n-----\n"])

    return "".join(message_list)


# ================================================
# PAPYRUS MONITORING / LOGGING
# ================================================
def papyrus_logging() -> tuple[str, int]:
    message_list: list[str] = []
    papyrus_path_setting = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Docs_File_PapyrusLog")
    papyrus_path = Path(papyrus_path_setting) if isinstance(papyrus_path_setting, str) else None

    count_dumps = count_stacks = count_warnings = count_errors = 0
    if papyrus_path and papyrus_path.exists():
        with CMain.open_file_with_encoding(papyrus_path) as papyrus_log:
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

        message_list.extend([f"NUMBER OF DUMPS     : {count_dumps} \n",
                             f"NUMBER OF STACKS     : {count_stacks} \n",
                             f"DUMPS/STACKS RATIO : {round(ratio, 3)} \n",
                             f"NUMBER OF WARNINGS : {count_warnings} \n",
                             f"NUMBER OF ERRORS   : {count_errors}"])
    else:
        message_list.extend(["[!] ERROR : UNABLE TO FIND *Papyrus.0.log* (LOGGING IS DISABLED OR YOU DIDN'T RUN THE GAME) \n",
                             "ENABLE PAPYRUS LOGGING MANUALLY OR WITH BETHINI AND START THE GAME TO GENERATE THE LOG FILE \n",
                             "BethINI Link | Use Manual Download : https://www.nexusmods.com/site/mods/631?tab=files \n"])

    message_output = "".join(message_list) # Debug print
    return message_output, count_dumps


# ================================================
# WRYE BASH - PLUGIN CHECKER
# ================================================
def scan_wryecheck() -> str:
    message_list: list[str] = []
    wrye_missinghtml_setting = CMain.yaml_settings(CMain.YAML.Game, "Warnings_MODS.Warn_WRYE_MissingHTML")
    wrye_plugincheck_setting = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Docs_File_WryeBashPC")
    wrye_warnings_setting = CMain.yaml_settings(CMain.YAML.Main, "Warnings_WRYE")

    wrye_missinghtml = wrye_missinghtml_setting if isinstance(wrye_missinghtml_setting, str) else None
    wrye_plugincheck = Path(wrye_plugincheck_setting) if isinstance(wrye_plugincheck_setting, str) else None
    wrye_warnings = wrye_warnings_setting if isinstance(wrye_warnings_setting, dict) else {}

    if wrye_plugincheck and Path(wrye_plugincheck).is_file():
        message_list.extend(["\n✔️ WRYE BASH PLUGIN CHECKER REPORT WAS FOUND! ANALYZING CONTENTS... \n",
                             f"  [This report is located in your Documents/My Games/{CMain.gamevars["game"]} folder.] \n",
                             "  [To hide this report, remove *ModChecker.html* from the same folder.] \n"])
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
                    message_list.append(f"\n   {"=" * left} {title} {"=" * right}\n")
                else:
                    message_list.append(title)

            if title == "ESL Capable":
                esl_count = sum(1 for _ in plugin_list)
                message_list.extend([f"❓ There are {esl_count} plugins that can be given the ESL flag. This can be done with \n",
                                     "  the SimpleESLify script to avoid reaching the plugin limit (254 esm/esp). \n",
                                     "  SimpleESLify: https://www.nexusmods.com/skyrimspecialedition/mods/27568 \n  -----\n"])

            for warn_name, warn_desc in wrye_warnings.items():
                if str(warn_name) in str(title):
                    message_list.append(str(warn_desc))

            if title not in {"ESL Capable", "Active Plugins:"}:
                message_list.extend([f"    > {elem} \n" for elem in plugin_list])

        message_list.extend(["\n❔ For more info about the above detected problems, see the WB Advanced Readme \n",
                             "  For more details about solutions, read the Advanced Troubleshooting Article \n",
                             "  Advanced Troubleshooting: https://www.nexusmods.com/fallout4/articles/4141 \n",
                             "  Wrye Bash Advanced Readme Documentation: https://wrye-bash.github.io/docs/ \n",
                             "  [ After resolving any problems, run Plugin Checker in Wrye Bash again! ] \n\n"])
    elif wrye_missinghtml is not None:
        message_list.append(wrye_missinghtml)
    else:
        raise ValueError("ERROR: Warnings_WRYE missing from the database!")

    return "".join(message_list)


# ================================================
# CHECK MOD INI FILES
# ================================================
def scan_mod_inis() -> str:  # Mod INI files check.
    message_list: list[str] = []
    vsync_list: list[str] = []
    game_root = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Root_Folder_Game")
    game_root_path = Path(game_root) if isinstance(game_root, str) else None


    files: list[str]
    if game_root_path:
        for root, _, files in game_root_path.walk():
            for file in files:
                ini_path = root / file
                if ini_path.suffix.lower() == ".ini":
                    with CMain.open_file_with_encoding(ini_path) as ini_file:
                        ini_data = ini_file.read()
                    if "sstartingconsolecommand" in ini_data.lower():
                        message_list.extend([f"[!] NOTICE: {ini_path} contains the *sStartingConsoleCommand* setting. \n",
                                            "In rare cases, this setting can slow down the initial game startup time for some players. \n",
                                            "You can test your initial startup time difference by removing this setting from the INI file. \n-----\n"])
                match file.lower():
                    case "dxvk.conf":
                        if mod_ini_config(ini_path, f"{CMain.gamevars["game"]}.exe", "dxgi.syncInterval") is True:
                            vsync_list.append(f"{ini_path} | SETTING: dxgi.syncInterval \n")
                    case "enblocal.ini":
                        if mod_ini_config(ini_path, "ENGINE", "ForceVSync") is True:
                            vsync_list.append(f"{ini_path} | SETTING: ForceVSync \n")
                    case "espexplorer.ini":
                        if "; F10" in mod_ini_config(ini_path, "General", "HotKey"):
                            mod_ini_config(ini_path, "General", "HotKey", "0x79")
                            CMain.logger.info(f"> > > PERFORMED INI HOTKEY FIX FOR {file}")
                            message_list.append(f"> Performed INI Hotkey Fix For : {file} \n")
                    case "epo.ini":
                        if int(mod_ini_config(ini_path, "Particles", "iMaxDesired")) > 5000:
                            mod_ini_config(ini_path, "Particles", "iMaxDesired", "5000")
                            CMain.logger.info(f"> > > PERFORMED INI PARTICLE COUNT FIX FOR {file}")
                            message_list.append(f"> Performed INI Particle Count Fix For : {file} \n")
                    case "f4ee.ini":
                        if mod_ini_config(ini_path, "CharGen", "bUnlockHeadParts") == 0:
                            mod_ini_config(ini_path, "CharGen", "bUnlockHeadParts", "1")
                            CMain.logger.info(f"> > > PERFORMED INI HEAD PARTS UNLOCK FOR {file}")
                            message_list.append(f"> Performed INI Head Parts Unlock For : {file} \n")
                        if mod_ini_config(ini_path, "CharGen", "bUnlockTints") == 0:
                            mod_ini_config(ini_path, "CharGen", "bUnlockTints", "1")
                            CMain.logger.info(f"> > > PERFORMED INI FACE TINTS UNLOCK FOR {file}")
                            message_list.append(f"> Performed INI Face Tints Unlock For : {file} \n")
                    case "fallout4_test.ini": # f-strings don't work in match-case statements as far as I can tell.
                        if mod_ini_config(ini_path, "CreationKit", "VSyncRender") is True: # CREATION KIT
                            vsync_list.append(f"{ini_path} | SETTING: VSyncRender \n")
                    case "highfpsphysicsfix.ini":
                        if mod_ini_config(ini_path, "Main", "EnableVSync"):
                            vsync_list.append(f"{ini_path} | SETTING: EnableVSync \n")
                        if float(mod_ini_config(ini_path, "Limiter", "LoadingScreenFPS")) < 600.0:
                            mod_ini_config(ini_path, "Limiter", "LoadingScreenFPS", "600.0")
                            CMain.logger.info(f"> > > PERFORMED INI LOADING SCREEN FPS FIX FOR {file}")
                            message_list.append(f"> Performed INI Loading Screen FPS Fix For : {file} \n")
                    case "longloadingtimesfix.ini":
                        if mod_ini_config(ini_path, "Limiter", "EnableVSync") is True:
                            vsync_list.append(f"{ini_path} | SETTING: EnableVSync \n")
                    case "reshade.ini":
                        if mod_ini_config(ini_path, "APP", "ForceVsync") is True:
                            vsync_list.append(f"{ini_path} | SETTING: ForceVsync \n")

    if vsync_list:
        message_list.append("* NOTICE : VSYNC IS CURRENTLY ENABLED IN THE FOLLOWING FILES * \n")
    return "".join(message_list) + "".join(vsync_list)


# ================================================
# CHECK ALL UNPACKED / LOOSE MOD FILES
# ================================================
def scan_mods_unpacked() -> str:
    message_list: list[str] = []
    cleanup_list: list[str] = []
    modscan_list: list[str] = []
    xse_acronym_setting = CMain.yaml_settings(CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.XSE_Acronym")
    xse_scriptfiles_setting = CMain.yaml_settings(CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.XSE_HashedScripts")

    xse_acronym = xse_acronym_setting if isinstance(xse_acronym_setting, str) else ""
    xse_scriptfiles = xse_scriptfiles_setting if isinstance(xse_scriptfiles_setting, dict) else {}

    backup_path = Path("CLASSIC Backup/Cleaned Files")
    backup_path.mkdir(parents=True, exist_ok=True)
    mod_folder = CMain.classic_settings("MODS Folder Path")
    mod_path = Path(mod_folder) if isinstance(mod_folder, str) else None
    if not mod_path:
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_Path_Missing")))
    elif not mod_path.is_dir():
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_Path_Invalid")))
    else:
        filter_names = ["readme", "changes", "changelog", "change log"]
        print("✔️ MODS FOLDER PATH FOUND! PERFORMING INITIAL MOD FILES CLEANUP...")
        for root, dirs, files in mod_path.walk(top_down=False):
            main_path = root.relative_to(mod_path)
            root_main = main_path.parts[1]
            for dirname in dirs:
                # ================================================
                # DETECT MODS WITH AnimationFileData
                if dirname.lower() == "animationfiledata":
                    modscan_list.append(f"[-] NOTICE (ANIMDATA) : {root_main} > CONTAINS CUSTOM ANIMATION FILE DATA \n")
                # ================================================
                # (RE)MOVE REDUNDANT FOMOD FOLDERS
                elif dirname.lower() == "fomod":
                    fomod_folder_path = root / dirname
                    relative_path = fomod_folder_path.relative_to(mod_path)
                    new_folder_path = backup_path / relative_path

                    cleanup_list.append(f"MOVED > {fomod_folder_path} FOLDER TO > {backup_path.as_posix()} \n")
                    shutil.move(fomod_folder_path, new_folder_path)

            for filename in files:
                # ================================================
                # DETECT DDS FILES WITH INCORRECT DIMENSIONS

                file_path = root / filename
                file_ext = file_path.suffix.lower()
                if file_ext == ".dds":
                    with file_path.open("rb") as dds_file:
                        dds_data = dds_file.read(20)
                    if dds_data[:4] == b"DDS ":
                        width = struct.unpack("<I", dds_data[12:16])[0]
                        height = struct.unpack("<I", dds_data[16:20])[0]
                        if width % 2 != 0 or height % 2 != 0:
                            modscan_list.append(f"[!] CAUTION (DDS-DIMS) : {file_path.as_posix()} > {width}x{height} > DDS DIMENSIONS ARE NOT DIVISIBLE BY 2 \n")
                # ================================================
                # DETECT INVALID TEXTURE FILE FORMATS
                elif file_ext in {".tga", ".png"}:
                    modscan_list.append(f"[-] NOTICE (-FORMAT-) : {file_path.as_posix()} > HAS THE WRONG TEXTURE FORMAT, SHOULD BE DDS \n")
                # ================================================
                # DETECT INVALID SOUND FILE FORMATS
                elif file_ext in {".mp3", ".m4a"}:
                    modscan_list.append(f"[-] NOTICE (-FORMAT-) : {root_main} > {filename} > HAS THE WRONG SOUND FORMAT, SHOULD BE XWM OR WAV \n")
                # ================================================
                # DETECT MODS WITH SCRIPT EXTENDER FILE COPIES
                elif any(filename.lower() == key.lower() for key in xse_scriptfiles) and "workshop framework" not in str(root).lower():
                    if f"Scripts\\{filename}" in str(file_path):
                        modscan_list.append(f"[!] CAUTION (XSE-COPY) : {root_main} > CONTAINS ONE OR SEVERAL COPIES OF *{xse_acronym}* SCRIPT FILES \n")
                # ================================================
                # DETECT MODS WITH PRECOMBINE / PREVIS FILES
                elif any(ext in filename.lower() for ext in (".uvd", "_oc.nif")):
                    modscan_list.append(f"[!] CAUTION (-PREVIS-) : {root_main} > CONTAINS LOOSE PRECOMBINE / PREVIS FILES \n")
                # ================================================
                # (RE)MOVE REDUNDANT README / CHANGELOG FILES
                elif file_ext == ".txt" and any(names.lower() in filename.lower() for names in filter_names):
                    relative_path = file_path.relative_to(mod_path)
                    new_file_path = backup_path / relative_path

                    # Create subdirectories if they don't exist.
                    new_file_path.parent.mkdir(parents=True, exist_ok=True)
                    cleanup_list.append(f"MOVED > {file_path} FILE TO > {backup_path.as_posix()} \n")
                    shutil.move(file_path, new_file_path)

        print("✔️ CLEANUP COMPLETE! NOW ANALYZING ALL UNPACKED/LOOSE MOD FILES...")
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_Reminders")))
        message_list.append("========= RESULTS FROM UNPACKED / LOOSE FILES =========\n")


    modscan_unique_list = sorted(set(modscan_list))
    return f"{"".join(message_list)}{"".join(cleanup_list)}{"".join(modscan_unique_list)}"


# ================================================
# CHECK ALL ARCHIVED / BA2 MOD FILES
# ================================================
def scan_mods_archived() -> str:
    message_list: list[str] = []
    modscan_list: list[str] = []
    xse_acronym_setting = CMain.yaml_settings(CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.XSE_Acronym")
    xse_scriptfiles_setting = CMain.yaml_settings(CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.XSE_HashedScripts")

    xse_acronym = xse_acronym_setting if isinstance(xse_acronym_setting, str) else ""
    xse_scriptfiles = xse_scriptfiles_setting if isinstance(xse_scriptfiles_setting, dict) else {}

    bsarch_path = Path.cwd() / "CLASSIC Data/BSArch.exe"
    mod_folder = CMain.classic_settings("MODS Folder Path")
    mod_path = Path(mod_folder) if isinstance(mod_folder, str) else None
    if not mod_path:
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_Path_Missing")))
    elif not mod_path.exists():
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_Path_Invalid")))
    elif not bsarch_path.exists():
        message_list.append(str(CMain.yaml_settings(CMain.YAML.Main, "Mods_Warn.Mods_BSArch_Missing")))
    else:
        print("✔️ ALL REQUIREMENTS SATISFIED! NOW ANALYZING ALL BA2 MOD ARCHIVES...")
        message_list.append("\n========== RESULTS FROM ARCHIVED / BA2 FILES ==========\n")
        for root, _, files in mod_path.walk(top_down=False):
            main_path = root.relative_to(mod_path)
            root_main = main_path.parts[1]
            for filename in files:
                file_path = root / filename

                if filename.lower().endswith("textures.ba2"):
                    command_dump = (bsarch_path, file_path, "-dump")
                    archived_dump = subprocess.run(command_dump, shell=True, capture_output=True, text=True, check=False)
                    if archived_dump.returncode != 0:
                        print("Command failed with error:\n", archived_dump.stderr)
                    else:
                        archived_output = archived_dump.stdout
                        # ================================================
                        # DETECT DDS FILES WITH INCORRECT DIMENSIONS
                        output_split = archived_output.split("\n")
                        output_list = [item for item in output_split if item]
                        for index, line in enumerate(output_list):
                            if ".dds" in line.lower():
                                dds_meta = output_list[index + 2]
                                dds_meta_split = dds_meta.split(":")
                                width = dds_meta_split[1].replace("  Height", "").strip()
                                height = dds_meta_split[2].replace("  CubeMap", "").strip()
                                if (width.isdecimal() and int(width) % 2 != 0) or (height.isdecimal() and int(height) % 2 != 0):
                                    modscan_list.append(f"[!] CAUTION (DDS-DIMS) : ({root_main}) {line} > {width}x{height} > DDS DIMENSIONS ARE NOT DIVISIBLE BY 2 \n")
                            # ================================================
                            # DETECT INVALID TEXTURE FILE FORMATS
                            elif any(ext in line.lower() for ext in (".tga", ".png")):
                                modscan_list.append(f"[-] NOTICE (-FORMAT-) : ({root_main}) {line} > HAS THE WRONG TEXTURE FORMAT, SHOULD BE DDS \n")

                elif filename.lower().endswith("main.ba2"):
                    command_list = (bsarch_path, file_path, "-list")
                    archived_list = subprocess.run(command_list, shell=True, capture_output=True, text=True, check=False)
                    if archived_list.returncode != 0:
                        print("BSArch command failed with the following error:\n", archived_list.stderr)
                    else:
                        archived_output = archived_list.stdout
                        # ================================================
                        # DETECT INVALID SOUND FILE FORMATS
                        if any(ext in archived_output.lower() for ext in (".mp3", ".m4a")):
                            modscan_list.append(f"[-] NOTICE (-FORMAT-) : {root_main} > BA2 ARCHIVE CONTAINS SOUND FILES IN THE WRONG FORMAT \n")
                        # ================================================
                        # DETECT MODS WITH AnimationFileData
                        if "animationfiledata" in archived_output.lower():
                            modscan_list.append(f"[-] NOTICE (ANIMDATA) : {root_main} > BA2 ARCHIVE CONTAINS CUSTOM ANIMATION FILE DATA \n")
                        # ================================================
                        # DETECT MODS WITH SCRIPT EXTENDER FILE COPIES
                        if any(f"scripts\\{key.lower()}" in archived_output.lower() for key in xse_scriptfiles) and "workshop framework" not in str(root).lower():
                            modscan_list.append(f"[!] CAUTION (XSE-COPY) : {root_main} > BA2 ARCHIVE CONTAINS ONE OR SEVERAL COPIES OF *{xse_acronym}* SCRIPT FILES \n")
                        # ================================================
                        # DETECT MODS WITH PRECOMBINE / PREVIS FILES
                        if any(ext in archived_output.lower()for ext in (".uvd", "_oc.nif")) and "previs repair pack" not in str(root).lower():
                            modscan_list.append(f"[-] NOTICE (-PREVIS-) : {root_main} > BA2 ARCHIVE CONTAINS CUSTOM PRECOMBINE / PREVIS FILES \n")

    modscan_unique_list = sorted(set(modscan_list))
    return "".join(message_list) + "".join(modscan_unique_list)


# ================================================
# BACKUP / RESTORE / REMOVE
# ================================================
def game_files_manage(classic_list: str, mode: Literal["BACKUP", "RESTORE", "REMOVE"] = "BACKUP") -> None:
    manage_list_setting = CMain.yaml_settings(CMain.YAML.Game, classic_list)
    game_path_setting = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Root_Folder_Game")

    manage_list = manage_list_setting if isinstance(manage_list_setting, list) else []
    game_path = Path(game_path_setting) if isinstance(game_path_setting, str) else None

    backup_path = Path(f"CLASSIC Backup/Game Files/{classic_list}")
    backup_path.mkdir(parents=True, exist_ok=True)
    game_files = list(game_path.glob("*")) if game_path else []
    list_name = classic_list.split(" ", 1)

    if mode == "BACKUP":
        print(f"CREATING A BACKUP OF {list_name[1]} FILES, PLEASE WAIT...")
        try:
            for file in game_files:
                if any(item.lower() in file.name.lower() for item in manage_list):
                    destination_file = backup_path / file.name
                    if file.is_file():
                        shutil.copy2(file, destination_file)
                    elif file.is_dir():
                        if destination_file.exists():
                            if destination_file.is_dir():
                                shutil.rmtree(destination_file)
                            else:
                                destination_file.unlink(missing_ok=True)
                        shutil.copytree(file, destination_file)
            print(f"✔️ SUCCESSFULLY CREATED A BACKUP OF {list_name[1]} FILES \n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO BACKUP {list_name[1]} FILES DUE TO FILE PERMISSIONS!")
            print("    TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")

    elif mode == "RESTORE":
        print(f"RESTORING {list_name[1]} FILES FROM A BACKUP, PLEASE WAIT...")
        try:
            for file in game_files:
                if any(item.lower() in file.name.lower() for item in manage_list):
                    destination_file = backup_path / file.name
                    if destination_file.is_file():
                        shutil.copy2(destination_file, file)
                    elif destination_file.is_dir():
                        if file.exists():
                            if file.is_dir():
                                shutil.rmtree(file)
                            else:
                                file.unlink(missing_ok=True)
                        shutil.copytree(destination_file, file)
            print(f"✔️ SUCCESSFULLY RESTORED {list_name[1]} FILES TO THE GAME FOLDER \n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO RESTORE {list_name[1]} FILES DUE TO FILE PERMISSIONS!")
            print("    TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")

    elif mode == "REMOVE":
        print(f"REMOVING {list_name[1]} FILES FROM YOUR GAME FOLDER, PLEASE WAIT...")
        try:
            for file in game_files:
                if any(item.lower() in file.name.lower() for item in manage_list):
                    if file.is_file():
                        file.unlink(missing_ok=True)
                    elif file.is_dir():
                        os.removedirs(file)
            print(f"✔️ SUCCESSFULLY REMOVED {list_name[1]} FILES FROM THE GAME FOLDER \n")
        except PermissionError:
            print(f"❌ ERROR : UNABLE TO REMOVE {list_name[1]} FILES DUE TO FILE PERMISSIONS!")
            print("  TRY RUNNING CLASSIC.EXE IN ADMIN MODE TO RESOLVE THIS PROBLEM.\n")


# ================================================
# COMBINED RESULTS
# ================================================
def game_combined_result() -> str:
    docs_path_setting = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Root_Folder_Docs")
    game_path_setting = CMain.yaml_settings(CMain.YAML.Game_Local, f"Game{CMain.gamevars["vr"]}_Info.Root_Folder_Game")

    docs_path = Path(docs_path_setting) if isinstance(docs_path_setting, str) else None
    game_path = Path(game_path_setting) if isinstance(game_path_setting, str) else None

    if game_path and docs_path:
        combined_return = [check_xse_plugins(), check_crashgen_settings(), check_log_errors(docs_path), check_log_errors(game_path), scan_wryecheck(), scan_mod_inis()]
        return "".join(combined_return)
    return ""


def mods_combined_result() -> str:  # KEEP THESE SEPARATE SO THEY ARE NOT INCLUDED IN AUTOSCAN REPORTS
    combined_return = [scan_mods_unpacked(), scan_mods_archived()]
    return "".join(combined_return)


def write_combined_results() -> None:
    game_result = game_combined_result()
    mods_result = mods_combined_result()
    gfs_report = Path("CLASSIC GFS Report.md")
    with gfs_report.open("w", encoding="utf-8", errors="ignore") as scan_report:
        scan_report.write(game_result + mods_result)


if __name__ == "__main__":
    CMain.initialize()
    CMain.main_generate_required()
    print(game_combined_result())
    print(mods_combined_result())
    game_files_manage("Backup ENB")
    os.system("pause")
