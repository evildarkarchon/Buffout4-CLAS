import os
import random
import shutil
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import regex as re
import requests
from packaging.version import Version

import CLASSIC_Main as CMain
import CLASSIC_ScanGame as CGame

query_cache: dict[tuple[str, str], str] = {}
# Define paths for both Main and Local databases
DB_PATHS = (
    Path(f"CLASSIC Data/databases/{CMain.gamevars["game"]} FormIDs Main.db"),
    Path(f"CLASSIC Data/databases/{CMain.gamevars["game"]} FormIDs Local.db"),
)


# ================================================
# ASSORTED FUNCTIONS
# ================================================
def pastebin_fetch(url: str) -> None:
    if urlparse(url).netloc == "pastebin.com" and "/raw" not in url:
        url = url.replace("pastebin.com", "pastebin.com/raw")
    response = requests.get(url)
    if response.status_code != requests.codes.ok:
        response.raise_for_status()
    pastebin_path = Path("Crash Logs/Pastebin")
    if not pastebin_path.is_dir():
        pastebin_path.mkdir(parents=True, exist_ok=True)
    outfile = pastebin_path / f"crash-{urlparse(url).path.split("/")[-1]}.log"
    outfile.write_text(response.text, encoding="utf-8", errors="ignore")


def get_entry(formid: str, plugin: str) -> str | None:
    if (entry := query_cache.get((formid, plugin))) is not None:
        return entry

    for db_path in DB_PATHS:
        if db_path.is_file():
            with sqlite3.connect(db_path) as conn:
                c = conn.cursor()
                c.execute(
                    f"SELECT entry FROM {CMain.gamevars["game"]} WHERE formid=? AND plugin=? COLLATE nocase",
                    (formid, plugin),
                )
                entry = c.fetchone()
                if entry:
                    query_cache[formid, plugin] = entry[0]
                    return entry[0]

    return None

# ================================================
# INITIAL REFORMAT FOR CRASH LOG FILES
# ================================================
def crashlogs_get_files() -> list[Path]:
    """Get paths of all available crash logs."""
    CMain.logger.debug("- - - INITIATED CRASH LOG FILE LIST GENERATION")
    CLASSIC_folder = Path.cwd()
    CLASSIC_logs = CLASSIC_folder / "Crash Logs"
    CLASSIC_pastebin = CLASSIC_logs / "Pastebin"
    CUSTOM_folder_setting = CMain.classic_settings(str, "SCAN Custom Path")
    XSE_folder_setting = CMain.yaml_settings(str, CMain.YAML.Game_Local, "Game_Info.Docs_Folder_XSE")

    CUSTOM_folder = Path(CUSTOM_folder_setting) if isinstance(CUSTOM_folder_setting, str) else None
    XSE_folder = Path(XSE_folder_setting) if isinstance(XSE_folder_setting, str) else None

    if not CLASSIC_logs.is_dir():
        CLASSIC_logs.mkdir(parents=True, exist_ok=True)
    if not CLASSIC_pastebin.is_dir():
        CLASSIC_pastebin.mkdir(parents=True, exist_ok=True)
    for file in CLASSIC_folder.glob("crash-*.log"):
        destination_file = CLASSIC_logs / file.name
        if not destination_file.is_file():
            file.rename(destination_file)
    for file in CLASSIC_folder.glob("crash-*-AUTOSCAN.md"):
        destination_file = CLASSIC_logs / file.name
        if not destination_file.is_file():
            file.rename(destination_file)
    if XSE_folder and XSE_folder.is_dir():
        for crash_file in XSE_folder.glob("crash-*.log"):
            destination_file = CLASSIC_logs / crash_file.name
            if not destination_file.is_file():
                shutil.copy2(crash_file, destination_file)

    crash_files = list(CLASSIC_logs.rglob("crash-*.log"))
    if CUSTOM_folder and CUSTOM_folder.is_dir():
        crash_files.extend(CUSTOM_folder.glob("crash-*.log"))

    return crash_files


def crashlogs_reformat(crashlog_list: list[Path], remove_list: list[str]) -> None:
    """Reformat plugin lists in crash logs, so that old and new CRASHGEN formats match."""
    CMain.logger.debug("- - - INITIATED CRASH LOG FILE REFORMAT")
    simplify_logs = CMain.classic_settings(bool, "Simplify Logs")

    for file in crashlog_list:
        with file.open(encoding="utf-8", errors="ignore") as crash_log:
            crash_data = crash_log.readlines()

        last_index = len(crash_data) - 1
        in_plugins = True
        for index, line in enumerate(reversed(crash_data)):
            if in_plugins and line.startswith("PLUGINS:"):
                in_plugins = False
            reversed_index = last_index - index
            if simplify_logs and any(string in line for string in remove_list):
                # Remove *useless* lines from crash log if Simplify Logs is enabled.
                crash_data.pop(reversed_index)
            elif in_plugins and "[" in line:
                # Replace all spaces inside the load order [brackets] with 0s.
                # This maintains consistency between different versions of Buffout 4.
                # Example log lines:
                # [ 1] DLCRobot.esm
                # [FE:  0] RedRocketsGlareII.esl
                indent, rest = line.split("[", 1)
                fid, name = rest.split("]", 1)
                crash_data[reversed_index] = f"{indent}[{fid.replace(" ", "0")}]{name}"

        with file.open("w", encoding="utf-8", errors="ignore") as crash_log:
            crash_log.writelines(crash_data)


def detect_mods_single(yaml_dict: dict[str, str], crashlog_plugins: dict[str, str], autoscan_report: list[str]) -> bool:
    """Detect one whole key (1 mod) per loop in YAML dict."""
    trigger_mod_found = False
    yaml_dict_lower = {key.lower(): value for key, value in yaml_dict.items()}
    crashlog_plugins_lower = {key.lower(): value for key, value in crashlog_plugins.items()}

    for mod_name_lower, mod_warn in yaml_dict_lower.items():
        for plugin_name_lower, plugin_fid in crashlog_plugins_lower.items():
            if mod_name_lower in plugin_name_lower:
                if mod_warn:
                    autoscan_report.extend((f"[!] FOUND : [{plugin_fid}] ", mod_warn))
                else:
                    raise ValueError(f"ERROR: {mod_name_lower} has no warning in the database!")
                trigger_mod_found = True
                break
    return trigger_mod_found


def detect_mods_double(yaml_dict: dict[str, str], crashlog_plugins: dict[str, str], autoscan_report: list[str]) -> bool:
    """Detect one split key (2 mods) per loop in YAML dict."""
    trigger_mod_found = False
    yaml_dict_lower = {key.lower(): value for key, value in yaml_dict.items()}
    crashlog_plugins_lower = {key.lower(): value for key, value in crashlog_plugins.items()}

    for mod_name_lower, mod_warn in yaml_dict_lower.items():
        mod_split = mod_name_lower.split(" | ", 1)
        mod1_found = mod2_found = False
        for plugin_name_lower in crashlog_plugins_lower:
            if not mod1_found and mod_split[0] in plugin_name_lower:
                mod1_found = True
                continue
            if not mod2_found and mod_split[1] in plugin_name_lower:
                mod2_found = True
                continue
        if mod1_found and mod2_found:
            if mod_warn:
                autoscan_report.extend(("[!] CAUTION : ", mod_warn))
            else:
                raise ValueError(f"ERROR: {mod_name_lower} has no warning in the database!")
            trigger_mod_found = True
    return trigger_mod_found

def detect_mods_important(
    yaml_dict: dict[str, str],
    crashlog_plugins: dict[str, str],
    autoscan_report: list[str],
    gpu_rival: Literal["nvidia", "amd"] | None,
) -> None:
    """Detect one important Core and GPU specific mod per loop in YAML dict."""
    for mod_name in yaml_dict:
        mod_warn = yaml_dict.get(mod_name, "")
        mod_split = mod_name.split(" | ", 1)
        mod_found = False
        for plugin_name in crashlog_plugins:
            if mod_split[0].lower() in plugin_name.lower():
                mod_found = True
                continue
        if mod_found:
            # noinspection PyTypeChecker
            if gpu_rival and gpu_rival in mod_warn.lower():
                autoscan_report.extend((
                    f"❓ {mod_split[1]} is installed, BUT IT SEEMS YOU DON'T HAVE AN {gpu_rival.upper()} GPU?\n",
                    "IF THIS IS CORRECT, COMPLETELY UNINSTALL THIS MOD TO AVOID ANY PROBLEMS! \n\n",
                ))
            else:
                autoscan_report.append(f"✔️ {mod_split[1]} is installed!\n\n")
        elif (gpu_rival and mod_warn) and gpu_rival not in mod_warn.lower():
            autoscan_report.extend((f"❌ {mod_split[1]} is not installed!\n", mod_warn, "\n"))


# Replacement for crashlog_generate_segment()
def find_segments(crash_data: list[str], xse_acronym: str, crashgen_name: str) -> tuple[str, str, str, list[list[str]]]:
    """Divide the log up into segments."""
    xse = xse_acronym.upper()
    segment_boundaries = (
        ("	[Compatibility]", "SYSTEM SPECS:"),  # segment_crashgen
        ("SYSTEM SPECS:", "PROBABLE CALL STACK:"),  # segment_system
        ("PROBABLE CALL STACK:", "MODULES:"),  # segment_callstack
        ("MODULES:", f"{xse} PLUGINS:"),  # segment_allmodules
        (f"{xse} PLUGINS:", "PLUGINS:"),  # segment_xsemodules
        ("PLUGINS:", "EOF"),  # segment_plugins
    )
    segment_index = 0
    collect = False
    segments: list[list[str]] = []
    next_boundary = segment_boundaries[0][0]
    index_start = 0
    total = len(crash_data)
    current_index = 0
    crashlog_gameversion = None
    crashlog_crashgen = None
    crashlog_mainerror = None
    game_root_name = CMain.yaml_settings(str, CMain.YAML.Game, f"Game_{CMain.gamevars["vr"]}Info.Main_Root_Name")
    while current_index < total:
        line = crash_data[current_index]
        if crashlog_gameversion is None and game_root_name and line.startswith(game_root_name):
            crashlog_gameversion = line.strip()
        if crashlog_crashgen is None:
            if line.startswith(crashgen_name):
                crashlog_crashgen = line.strip()
        elif crashlog_mainerror is None and line.startswith("Unhandled exception"):
            crashlog_mainerror = line.replace("|", "\n", 1)

        elif line.startswith(next_boundary):
            if collect:
                index_end = current_index - 1 if current_index > 0 else current_index
                segments.append(crash_data[index_start:index_end])
                segment_index += 1
                if segment_index == len(segment_boundaries):
                    break
            else:
                index_start = current_index + 1 if total > current_index else current_index
            collect = not collect
            next_boundary = segment_boundaries[segment_index][collect]
            if collect:
                if next_boundary == "EOF":
                    segments.append(crash_data[index_start:])
                    break
            else:
                # Don't increase current_index in case the current
                # line is also the next start boundary
                continue
        current_index += 1
        if collect and current_index == total:
            segments.append(crash_data[index_start:])

    segment_results = [[line.strip() for line in segment] for segment in segments] if segments else segments
    missing_segments = len(segment_boundaries) - len(segment_results)
    if missing_segments > 0:
        segment_results.extend([[]] * missing_segments)
    # Set default values incase actual index is not found.
    return crashlog_gameversion or "UNKNOWN", crashlog_crashgen or "UNKNOWN", crashlog_mainerror or "UNKNOWN", segment_results


def crashgen_version_gen(input_string: str) -> Version:
    input_string = input_string.strip()
    parts = input_string.split()
    version_str = ""
    for part in parts:
        if part.startswith("v") and len(part) > 1:
            version_str = part[1:]  # Remove the 'v'
    if version_str:
        return Version(version_str)
    return Version("0.0.0")

class SQLiteReader:
    def __init__(self, logfiles: list[Path]) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE crashlogs (logname TEXT UNIQUE, logdata BLOB)")
        self.db.execute("CREATE INDEX idx_logname ON crashlogs (logname)")
        self.db.executemany("INSERT INTO crashlogs VALUES (?, ?)", ((file.name, file.read_bytes()) for file in logfiles))

    def read_log(self, logname: str) -> list[str]:
        with self.db as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT logdata FROM crashlogs WHERE logname = ?", (logname,))
            return cursor.fetchone()[0].decode("utf-8", errors="ignore").splitlines()

    def close(self) -> None:
        self.db.close()

@dataclass
class ClassicScanLogsInfo:
    classic_game_hints: list[str] = field(default_factory=list)
    classic_records_list: list[str] = field(default_factory=list)
    classic_version: str = ""
    classic_version_date: str = ""
    crashgen_name: str = ""
    crashgen_latest_og: str = ""
    crashgen_latest_vr: str = ""
    crashgen_ignore: set = field(default_factory=set)
    warn_noplugins: str = ""
    warn_outdated: str = ""
    xse_acronym: str = ""
    game_ignore_plugins: list[str] = field(default_factory=list)
    game_ignore_records: list[str] = field(default_factory=list)
    suspects_error_list: dict[str, str] = field(default_factory=dict)
    suspects_stack_list: dict[str, list[str]] = field(default_factory=dict)
    autoscan_text: str = ""
    ignore_list: list[str] = field(default_factory=list)
    game_mods_conf: dict[str, str] = field(default_factory=dict)
    game_mods_core: dict[str, str] = field(default_factory=dict)
    game_mods_core_folon: dict[str, str] = field(default_factory=dict)
    game_mods_freq: dict[str, str] = field(default_factory=dict)
    game_mods_opc2: dict[str, str] = field(default_factory=dict)
    game_mods_solu: dict[str, str] = field(default_factory=dict)
    game_version: Version = field(default=Version("0.0.0"), init=False)
    game_version_new: Version = field(default=Version("0.0.0"), init=False)
    game_version_vr: Version = field(default=Version("0.0.0"), init=False)



    def __post_init__(self) -> None:
        if CMain.yaml_cache is None:
            raise TypeError("CMain is not initialized.")
        self.classic_game_hints = CMain.yaml_settings(list[str], CMain.YAML.Game, "Game_Hints") or []
        self.classic_records_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "catch_log_records") or []
        self.classic_version=CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version") or ""
        self.classic_version_date=CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version_date") or ""
        self.crashgen_name=CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LogName") or ""
        self.crashgen_latest_og=CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LatestVer") or ""
        self.crashgen_latest_vr=CMain.yaml_settings(str, CMain.YAML.Game, "GameVR_Info.CRASHGEN_LatestVer") or ""
        self.crashgen_ignore=set(CMain.yaml_settings(list[str], CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.CRASHGEN_Ignore") or [])
        self.warn_noplugins=CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_NOPlugins") or ""
        self.warn_outdated=CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_Outdated") or ""
        self.xse_acronym=CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.XSE_Acronym") or ""
        self.game_ignore_plugins=CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Plugins_Exclude") or []
        self.game_ignore_records=CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Records_Exclude") or []
        self.suspects_error_list=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Crashlog_Error_Check") or {}
        self.suspects_stack_list=CMain.yaml_settings(dict[str, list[str]], CMain.YAML.Game, "Crashlog_Stack_Check") or {}
        self.autoscan_text=CMain.yaml_settings(str, CMain.YAML.Main, f"CLASSIC_Interface.autoscan_text_{CMain.gamevars['game']}") or ""
        self.ignore_list=CMain.yaml_settings(list[str], CMain.YAML.Ignore, f"CLASSIC_Ignore_{CMain.gamevars['game']}") or []
        self.game_mods_conf=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CONF") or {}
        self.game_mods_core=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE") or {}
        self.game_mods_core_folon=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE_FOLON") or {}
        self.game_mods_freq=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_FREQ") or {}
        self.game_mods_opc2=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_OPC2") or {}
        self.game_mods_solu=CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_SOLU") or {}
        self.game_version = Version(CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.GameVersion") or "0.0.0")
        self.game_version_new = Version(CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.GameVersionNEW") or "0.0.0")
        self.game_version_vr = Version(CMain.yaml_settings(str, CMain.YAML.Game, "GameVR_Info.GameVersion") or "0.0.0")

# ================================================
# CRASH LOG SCAN START
# ================================================
def crashlogs_scan() -> None:
    pluginsearch = re.compile(r"\s*\[(FE:([0-9A-F]{3})|[0-9A-F]{2})\]\s*(.+?(?:\.es[pml])+)", flags=re.IGNORECASE)
    crashlog_list = crashlogs_get_files()
    print("REFORMATTING CRASH LOGS, PLEASE WAIT...\n")
    remove_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_records") or []
    crashlogs_reformat(crashlog_list, remove_list)

    print("SCANNING CRASH LOGS, PLEASE WAIT...\n")
    scan_start_time = time.perf_counter()
    # ================================================
    # Grabbing YAML values is time expensive, so keep these out of the main file loop.
    yamldata = ClassicScanLogsInfo()  # Moved to a class for better organization.

    xse_acronym = yamldata.xse_acronym.lower()
    fcx_mode = CMain.classic_settings(bool, "FCX Mode")
    show_formid_values = CMain.classic_settings(bool, "Show FormID Values")
    formid_db_exists = any(db.is_file() for db in DB_PATHS)
    move_unsolved_logs = CMain.classic_settings(bool, "Move Unsolved Logs")
    lower_records = [record.lower() for record in yamldata.classic_records_list]
    lower_ignore = [record.lower() for record in yamldata.game_ignore_records]
    lower_plugins_ignore = {ignore.lower() for ignore in yamldata.game_ignore_plugins}
    ignore_plugins_list = {item.lower() for item in yamldata.ignore_list} if yamldata.ignore_list else set()
    # ================================================
    if fcx_mode:
        main_files_check = CMain.main_combined_result()
        game_files_check = CGame.game_combined_result()
    else:
        main_files_check = "❌ FCX Mode is disabled, skipping game files check... \n-----\n"
        game_files_check = ""

    scan_failed_list: list[str] = []
    user_folder = Path.home()
    stats_crashlog_scanned = stats_crashlog_incomplete = stats_crashlog_failed = 0
    CMain.logger.info(f"- - - INITIATED CRASH LOG FILE SCAN >>> CURRENTLY SCANNING {len(crashlog_list)} FILES")

    crashlogs = SQLiteReader(crashlog_list)

    for crashlog_file in crashlog_list:
        autoscan_report: list[str] = []
        trigger_plugin_limit = trigger_limit_check_disabled = trigger_plugins_loaded = trigger_scan_failed = False
        crash_data = crashlogs.read_log(crashlog_file.name)

        autoscan_report.extend((
            f"{crashlog_file.name} -> AUTOSCAN REPORT GENERATED BY {yamldata.classic_version} \n",
            "# FOR BEST VIEWING EXPERIENCE OPEN THIS FILE IN NOTEPAD++ OR SIMILAR # \n",
            "# PLEASE READ EVERYTHING CAREFULLY AND BEWARE OF FALSE POSITIVES # \n",
            "====================================================\n",
        ))

        # ================================================
        # 1) GENERATE REQUIRED SEGMENTS FROM THE CRASH LOG
        # ================================================
        (
            crashlog_gameversion,
            crashlog_crashgen,
            crashlog_mainerror,
            (
                segment_crashgen,
                segment_system,
                segment_callstack,
                segment_allmodules,
                segment_xsemodules,
                segment_plugins,
            ),
        ) = find_segments(crash_data, xse_acronym, yamldata.crashgen_name)
        segment_callstack_intact = "".join(segment_callstack)

        game_version = crashgen_version_gen(crashlog_gameversion)

        # SOME IMPORTANT DLLs HAVE A VERSION, REMOVE IT
        segment_xsemodules_lower = {x.lower() for x in segment_xsemodules}
        xsemodules = (
            {x.split(" v", 1)[0].strip() if "dll v" in x else x.strip() for x in segment_xsemodules_lower}
            if segment_xsemodules
            else set()
        )
        crashgen: dict[str, bool | int | str] = {}
        if segment_crashgen:
            for elem in segment_crashgen:
                if ":" in elem:
                    key, value = elem.split(":", 1)
                    crashgen[key] = True if value == " true" else False if value == " false" else int(value) if value.isdecimal() else value.strip()

        if not segment_plugins:
            stats_crashlog_incomplete += 1
        if len(crash_data) < 20:
            stats_crashlog_scanned -= 1
            stats_crashlog_failed += 1
            trigger_scan_failed = True

        # ================== MAIN ERROR ==================
        # =============== CRASHGEN VERSION ===============
        version_current = crashgen_version_gen(crashlog_crashgen)
        version_latest = crashgen_version_gen(yamldata.crashgen_latest_og)
        version_latest_vr = crashgen_version_gen(yamldata.crashgen_latest_vr)
        autoscan_report.extend((
            f"\nMain Error: {crashlog_mainerror}\n",
            f"Detected {yamldata.crashgen_name} Version: {crashlog_crashgen} \n",
            (
                f"* You have the latest version of {yamldata.crashgen_name}! *\n\n"
                if version_current >= version_latest or version_current >= version_latest_vr
                else f"{yamldata.warn_outdated} \n"
            ),
        ))

        # ======= REQUIRED LISTS, DICTS AND CHECKS =======

        crashlog_plugins: dict[str, str] = {}

        esm_name = f"{CMain.gamevars["game"]}.esm"
        if any(esm_name in elem for elem in segment_plugins):
            trigger_plugins_loaded = True
        else:
            stats_crashlog_incomplete += 1

        # ================================================
        # 2) CHECK EACH SEGMENT AND CREATE REQUIRED VALUES
        # ================================================

        # CHECK GPU TYPE FOR CRASH LOG
        crashlog_GPUAMD = any("GPU #1" in elem and "AMD" in elem for elem in segment_system)
        crashlog_GPUNV = any("GPU #1" in elem and "Nvidia" in elem for elem in segment_system)
        crashlog_GPUI = not crashlog_GPUAMD and not crashlog_GPUNV
        gpu_rival: Literal["nvidia", "amd"] | None = "nvidia" if (crashlog_GPUAMD or crashlog_GPUI) else "amd" if crashlog_GPUNV else None

        # IF LOADORDER FILE EXISTS, USE ITS PLUGINS
        loadorder_path = Path("loadorder.txt")
        if loadorder_path.exists():
            autoscan_report.extend((
                "* ✔️ LOADORDER.TXT FILE FOUND IN THE MAIN CLASSIC FOLDER! *\n",
                "CLASSIC will now ignore plugins in all crash logs and only detect plugins in this file.\n",
                "[ To disable this functionality, simply remove loadorder.txt from your CLASSIC folder. ]\n\n",
            ))
            with loadorder_path.open(encoding="utf-8", errors="ignore") as loadorder_file:
                loadorder_data = loadorder_file.readlines()
            for elem in loadorder_data[1:]:
                if all(elem not in item for item in crashlog_plugins):
                    crashlog_plugins[elem] = "LO"
            trigger_plugins_loaded = True

        else:  # OTHERWISE, USE PLUGINS FROM CRASH LOG
            for elem in segment_plugins:
                if "[FF]" in elem:
                    if game_version in (yamldata.game_version, yamldata.game_version_vr):
                        trigger_plugin_limit = True
                    elif game_version >= yamldata.game_version_new:
                        trigger_limit_check_disabled = True
                pluginmatch = pluginsearch.match(elem, concurrent=True)
                if pluginmatch is not None:
                    plugin_fid = pluginmatch.group(1)
                    plugin_name = pluginmatch.group(3)
                    if plugin_fid is not None and all(plugin_name not in item for item in crashlog_plugins):
                        crashlog_plugins[plugin_name] = plugin_fid.replace(":", "")
                    elif plugin_name and "dll" in plugin_name.lower():
                        crashlog_plugins[plugin_name] = "DLL"
                    else:
                        crashlog_plugins[plugin_name] = "???"

        for elem in xsemodules:
            if all(elem not in item for item in crashlog_plugins):
                crashlog_plugins[elem] = "DLL"

        for elem in segment_allmodules:
            # SOME IMPORTANT DLLs ONLY APPEAR UNDER ALL MODULES
            if "vulkan" in elem.lower():
                elem_parts = elem.strip().split(" ", 1)
                elem_parts[1] = "DLL"
                if all(elem_parts[0] not in item for item in crashlog_plugins):
                    crashlog_plugins[elem_parts[0]] = elem_parts[1]

        crashlog_plugins_lower = {plugin.lower() for plugin in crashlog_plugins}

        # CHECK IF THERE ARE ANY PLUGINS IN THE IGNORE YAML
        if ignore_plugins_list:
            for signal in ignore_plugins_list:
                if any(signal == plugin for plugin in crashlog_plugins_lower):
                    del crashlog_plugins[signal]

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING IF LOG MATCHES ANY KNOWN CRASH SUSPECTS...\n",
            "====================================================\n",
        ))

        crashlog_mainerror_lower = crashlog_mainerror.lower()
        if ".dll" in crashlog_mainerror_lower and "tbbmalloc" not in crashlog_mainerror_lower:
            autoscan_report.extend((
                "* NOTICE : MAIN ERROR REPORTS THAT A DLL FILE WAS INVOLVED IN THIS CRASH! * \n",
                "If that dll file belongs to a mod, that mod is a prime suspect for the crash. \n-----\n",
            ))
        max_warn_length = 30
        trigger_suspect_found = False
        for error, signal in yamldata.suspects_error_list.items():
            error_severity, error_name = error.split(" | ", 1)
            if signal in crashlog_mainerror:
                error_name = error_name.ljust(max_warn_length, ".")
                autoscan_report.append(f"# Checking for {error_name} SUSPECT FOUND! > Severity : {error_severity} # \n-----\n")
                trigger_suspect_found = True

        for error in yamldata.suspects_stack_list:
            error_severity, error_name = error.split(" | ", 1)
            error_req_found = error_opt_found = stack_found = False
            signal_list = yamldata.suspects_stack_list.get(error, [])
            has_required_item = False
            for signal in signal_list:
                if "|" in signal:
                    signal_modifier, signal_string = signal.split("|", 1)
                    match signal_modifier:
                        case "ME-REQ":
                            has_required_item = True
                            if signal_string in crashlog_mainerror:
                                error_req_found = True
                        case "ME-OPT":
                            if signal_string in crashlog_mainerror:
                                error_opt_found = True
                        case "NOT" if signal_string in segment_callstack_intact:
                            break
                        case _ if signal_modifier.isdecimal():
                            if segment_callstack_intact.count(signal_string) >= int(signal_modifier):
                                stack_found = True
                elif signal in segment_callstack_intact:
                    stack_found = True

            # print(f"TEST: {error_req_found} | {error_opt_found} | {stack_found}")
            if has_required_item:
                if error_req_found:
                    error_name = error_name.ljust(max_warn_length, ".")
                    autoscan_report.append(f"# Checking for {error_name} SUSPECT FOUND! > Severity : {error_severity} # \n-----\n")
                    trigger_suspect_found = True
            elif error_opt_found or stack_found:
                error_name = error_name.ljust(max_warn_length, ".")
                autoscan_report.append(f"# Checking for {error_name} SUSPECT FOUND! > Severity : {error_severity} # \n-----\n")
                trigger_suspect_found = True

        if trigger_suspect_found:
            autoscan_report.extend((
                "* FOR DETAILED DESCRIPTIONS AND POSSIBLE SOLUTIONS TO ANY ABOVE DETECTED CRASH SUSPECTS *\n",
                "* SEE: https://docs.google.com/document/d/17FzeIMJ256xE85XdjoPvv_Zi3C5uHeSTQh6wOZugs4c *\n\n",
            ))
        else:
            autoscan_report.extend((
                "# FOUND NO CRASH ERRORS / SUSPECTS THAT MATCH THE CURRENT DATABASE #\n",
                "Check below for mods that can cause frequent crashes and other problems.\n\n",
            ))

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING IF NECESSARY FILES/SETTINGS ARE CORRECT...\n",
            "====================================================\n",
        ))

        Has_XCell = ("x-cell-fo4.dll" in xsemodules or "x-cell-og.dll" in xsemodules or "x-cell-ng2.dll" in xsemodules)
        Has_BakaScrapHeap = "bakascrapheap.dll" in xsemodules

        if fcx_mode:
            autoscan_report.extend((
                "* NOTICE: FCX MODE IS ENABLED. CLASSIC MUST BE RUN BY THE ORIGINAL USER FOR CORRECT DETECTION * \n",
                "[ To disable mod & game files detection, disable FCX Mode in the exe or CLASSIC Settings.yaml ] \n\n",
            ))

        else:
            autoscan_report.extend((
                "* NOTICE: FCX MODE IS DISABLED. YOU CAN ENABLE IT TO DETECT PROBLEMS IN YOUR MOD & GAME FILES * \n",
                "[ FCX Mode can be enabled in the exe or CLASSIC Settings.yaml located in your CLASSIC folder. ] \n\n",
            ))
            if Has_XCell:
                yamldata.crashgen_ignore.update(("MemoryManager", "HavokMemorySystem", "ScaleformAllocator", "SmallBlockAllocator"))
            elif Has_BakaScrapHeap:
                # To prevent two messages mentioning this parameter.
                yamldata.crashgen_ignore.add("MemoryManager")

            if crashgen:
                for setting_name, setting_value in crashgen.items():
                    if setting_value is False and setting_name not in yamldata.crashgen_ignore:
                        autoscan_report.append(
                            f"* NOTICE : {setting_name} is disabled in your {yamldata.crashgen_name} settings, is this intentional? * \n-----\n"
                        )
                crashgen_achievements = crashgen.get("Achievements")
                if crashgen_achievements is not None:
                    if crashgen_achievements and ("achievements.dll" in xsemodules or "unlimitedsurvivalmode.dll" in xsemodules):
                        autoscan_report.extend((
                            "# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE # \n",
                            f" FIX: Open {yamldata.crashgen_name}'s TOML file and change Achievements to FALSE, this prevents conflicts with {yamldata.crashgen_name}.\n-----\n",
                        ))
                    else:
                        autoscan_report.append(
                            f"✔️ Achievements parameter is correctly configured in your {yamldata.crashgen_name} settings! \n-----\n"
                        )
                crashgen_memorymanager = crashgen.get("MemoryManager")
                if crashgen_memorymanager is not None:
                    if crashgen_memorymanager:
                        if Has_XCell:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but MemoryManager parameter is set to TRUE # \n",
                                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change MemoryManager to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                            if Has_BakaScrapHeap:
                                autoscan_report.extend((
                                    "# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with X-Cell # \n",
                                    " FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with X-Cell.\n-----\n",
                                ))
                        elif Has_BakaScrapHeap:
                            autoscan_report.extend((
                                f"# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with {yamldata.crashgen_name} # \n",
                                f" FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with {yamldata.crashgen_name}.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ Memory Manager parameter is correctly configured in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                    elif Has_XCell:
                        if Has_BakaScrapHeap:
                            autoscan_report.extend((
                                "# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with X-Cell # \n",
                                " FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ Memory Manager parameter is correctly configured for use with X-Cell in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                    elif Has_BakaScrapHeap:
                        autoscan_report.extend((
                            f"# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with {yamldata.crashgen_name} # \n",
                            f" FIX: Uninstall the Baka ScrapHeap Mod and open {yamldata.crashgen_name}'s TOML file and change MemoryManager to TRUE, this improves performance.\n-----\n",
                        ))

                if Has_XCell:
                    crashgen_havokmemorysystem = crashgen.get("HavokMemorySystem")
                    if crashgen_havokmemorysystem is not None:
                        if crashgen_havokmemorysystem:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but HavokMemorySystem parameter is set to TRUE # \n",
                                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change HavokMemorySystem to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ HavokMemorySystem parameter is correctly configured for use with X-Cell in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                    crashgen_bstexturestreamerlocalheap = crashgen.get("BSTextureStreamerLocalHeap")
                    if crashgen_bstexturestreamerlocalheap is not None:
                        if crashgen_bstexturestreamerlocalheap:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but BSTextureStreamerLocalHeap parameter is set to TRUE # \n",
                                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change BSTextureStreamerLocalHeap to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ BSTextureStreamerLocalHeap parameter is correctly configured for use with X-Cell in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                    crashgen_scaleformallocator = crashgen.get("ScaleformAllocator")
                    if crashgen_scaleformallocator is not None:
                        if crashgen_scaleformallocator:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but ScaleformAllocator parameter is set to TRUE # \n",
                                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change ScaleformAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ ScaleformAllocator parameter is correctly configured for use with X-Cell in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                    crashgen_smallblockallocator = crashgen.get("SmallBlockAllocator")
                    if crashgen_smallblockallocator is not None:
                        if crashgen_smallblockallocator:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but SmallBlockAllocator parameter is set to TRUE # \n",
                                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change SmallBlockAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        else:
                            autoscan_report.append(
                                f"✔️ SmallBlockAllocator parameter is correctly configured for use with X-Cell in your {yamldata.crashgen_name} settings! \n-----\n"
                            )
                crashgen_f4ee = crashgen.get("F4EE")
                if crashgen_f4ee is not None:
                    if not crashgen_f4ee and "f4ee.dll" in xsemodules:
                        autoscan_report.extend((
                            "# ❌ CAUTION : Looks Menu is installed, but F4EE parameter under [Compatibility] is set to FALSE # \n",
                            f" FIX: Open {yamldata.crashgen_name}'s TOML file and change F4EE to TRUE, this prevents bugs and crashes from Looks Menu.\n-----\n",
                        ))
                    else:
                        autoscan_report.append(
                            f"✔️ F4EE (Looks Menu) parameter is correctly configured in your {yamldata.crashgen_name} settings! \n-----\n"
                        )

        autoscan_report.append(main_files_check)
        if game_files_check:
            autoscan_report.append(game_files_check)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING FOR MODS THAT CAN CAUSE FREQUENT CRASHES...\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if detect_mods_single(yamldata.game_mods_freq, crashlog_plugins, autoscan_report):
                autoscan_report.extend((
                    "# [!] CAUTION : ANY ABOVE DETECTED MODS HAVE A MUCH HIGHER CHANCE TO CRASH YOUR GAME! #\n",
                    "* YOU CAN DISABLE ANY / ALL OF THEM TEMPORARILY TO CONFIRM THEY CAUSED THIS CRASH. * \n\n",
                ))
            else:
                autoscan_report.extend((
                    "# FOUND NO PROBLEMATIC MODS THAT MATCH THE CURRENT DATABASE FOR THIS CRASH LOG #\n",
                    "THAT DOESN'T MEAN THERE AREN'T ANY! YOU SHOULD RUN PLUGIN CHECKER IN WRYE BASH \n",
                    "Plugin Checker Instructions: https://www.nexusmods.com/fallout4/articles/4141 \n\n",
                ))
        else:
            autoscan_report.append(yamldata.warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING FOR MODS THAT CONFLICT WITH OTHER MODS...\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if detect_mods_double(yamldata.game_mods_conf, crashlog_plugins, autoscan_report):
                autoscan_report.extend((
                    "# [!] CAUTION : FOUND MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n",
                    "* YOU SHOULD CHOOSE WHICH MOD TO KEEP AND DISABLE OR COMPLETELY REMOVE THE OTHER MOD * \n\n",
                ))
            else:
                autoscan_report.append("# FOUND NO MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n\n")
        else:
            autoscan_report.append(yamldata.warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING FOR MODS WITH SOLUTIONS & COMMUNITY PATCHES\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if detect_mods_single(yamldata.game_mods_solu, crashlog_plugins, autoscan_report):
                autoscan_report.extend((
                    "# [!] CAUTION : FOUND PROBLEMATIC MODS WITH SOLUTIONS AND COMMUNITY PATCHES # \n",
                    "[Due to limitations, CLASSIC will show warnings for some mods even if fixes or patches are already installed.] \n",
                    "[To hide these warnings, you can add their plugin names to the CLASSIC Ignore.yaml file. ONE PLUGIN PER LINE.] \n\n",
                ))
            else:
                autoscan_report.append("# FOUND NO PROBLEMATIC MODS WITH AVAILABLE SOLUTIONS AND COMMUNITY PATCHES # \n\n")
        else:
            autoscan_report.append(yamldata.warn_noplugins)

        if CMain.gamevars["game"] == "Fallout4":
            autoscan_report.extend((
                "====================================================\n",
                "CHECKING FOR MODS PATCHED THROUGH OPC INSTALLER...\n",
                "====================================================\n",
            ))

            if trigger_plugins_loaded:
                if detect_mods_single(yamldata.game_mods_opc2, crashlog_plugins, autoscan_report):
                    autoscan_report.extend((
                        "\n* FOR PATCH REPOSITORY THAT PREVENTS CRASHES AND FIXES PROBLEMS IN THESE AND OTHER MODS,* \n",
                        "* VISIT OPTIMIZATION PATCHES COLLECTION: https://www.nexusmods.com/fallout4/mods/54872 * \n\n",
                    ))
                else:
                    autoscan_report.append("# FOUND NO PROBLEMATIC MODS THAT ARE ALREADY PATCHED THROUGH THE OPC INSTALLER # \n\n")
            else:
                autoscan_report.append(yamldata.warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING IF IMPORTANT PATCHES & FIXES ARE INSTALLED\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if any("londonworldspace" in plugin.lower() for plugin in crashlog_plugins):
                detect_mods_important(yamldata.game_mods_core_folon, crashlog_plugins, autoscan_report, gpu_rival)
            else:
                detect_mods_important(yamldata.game_mods_core, crashlog_plugins, autoscan_report, gpu_rival)
        else:
            autoscan_report.append(yamldata.warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "SCANNING THE LOG FOR SPECIFIC (POSSIBLE) SUSPECTS...\n",
            "====================================================\n",
        ))

        if trigger_plugin_limit and not trigger_limit_check_disabled:
            warn_plugin_limit = CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Plugin_Limit") or ""
            autoscan_report.append(warn_plugin_limit)

        if trigger_limit_check_disabled:
            autoscan_report.extend(("❌ WARNING : Crash logs for the current game version do not report plugin indexes correctly! \n",
                                                "The plugin limit check will be disabled for this scan. \n\n"))

        # ================================================

        autoscan_report.append("# LIST OF (POSSIBLE) PLUGIN SUSPECTS #\n")
        segment_callstack_lower = [line.lower() for line in segment_callstack]

        plugins_matches: list[str] = [
            plugin
            for line in segment_callstack_lower
            for plugin in crashlog_plugins_lower
            if plugin in line and "modified by:" not in line and all(ignore not in plugin for ignore in lower_plugins_ignore)
        ]

        if plugins_matches:
            plugins_found = dict(Counter(plugins_matches))
            if plugins_found:
                autoscan_report.extend([f"- {key} | {value}\n" for key, value in plugins_found.items()])
                autoscan_report.extend((
                    "\n[Last number counts how many times each Plugin Suspect shows up in the crash log.]\n",
                    f"These Plugins were caught by {yamldata.crashgen_name} and some of them might be responsible for this crash.\n",
                    "You can try disabling these plugins and check if the game still crashes, though this method can be unreliable.\n\n",
                ))
        else:
            autoscan_report.append("* COULDN'T FIND ANY PLUGIN SUSPECTS *\n\n")

        # ================================================
        autoscan_report.append("# LIST OF (POSSIBLE) FORM ID SUSPECTS #\n")
        formids_matches = [line.replace("0x", "").strip() for line in segment_callstack if "0xFF" not in line and "id:" in line.lower()]
        if formids_matches:
            formids_found = dict(Counter(sorted(formids_matches)))
            for formid_full, count in formids_found.items():
                formid_split = formid_full.split(": ", 1)
                if len(formid_split) < 2:
                    continue
                for plugin, plugin_id in crashlog_plugins.items():
                    if plugin_id != formid_split[1][:2]:
                        continue

                    if show_formid_values and formid_db_exists:
                        report = get_entry(formid_split[1][2:], plugin)
                        if report:
                            autoscan_report.append(f"- {formid_full} | [{plugin}] | {report} | {count}\n")
                            continue

                    autoscan_report.append(f"- {formid_full} | [{plugin}] | {count}\n")
                    break

            autoscan_report.extend((
                "\n[Last number counts how many times each Form ID shows up in the crash log.]\n",
                f"These Form IDs were caught by {yamldata.crashgen_name} and some of them might be related to this crash.\n",
                "You can try searching any listed Form IDs in xEdit and see if they lead to relevant records.\n\n",
            ))
        else:
            autoscan_report.append("* COULDN'T FIND ANY FORM ID SUSPECTS *\n\n")

        # ================================================

        autoscan_report.append("# LIST OF DETECTED (NAMED) RECORDS #\n")
        records_matches: list[str] = []

        for line in segment_callstack:
            lower_line = line.lower()

            if any(item in lower_line for item in lower_records) and all(
                record not in lower_line for record in lower_ignore
            ):
                if "[RSP+" in line:
                    records_matches.append(line[30:].strip())
                else:
                    records_matches.append(line.strip())
        if records_matches:
            records_found = dict(Counter(sorted(records_matches)))
            for record, count in records_found.items():
                autoscan_report.append(f"- {record} | {count}\n")

            autoscan_report.extend((
                "\n[Last number counts how many times each Named Record shows up in the crash log.]\n",
                f"These records were caught by {yamldata.crashgen_name} and some of them might be related to this crash.\n",
                "Named records should give extra info on involved game objects, record types or mod files.\n\n",
            ))
        else:
            autoscan_report.append("* COULDN'T FIND ANY NAMED RECORDS *\n\n")

        # ============== AUTOSCAN REPORT END ==============
        if CMain.gamevars["game"] == "Fallout4":
            autoscan_report.append(yamldata.autoscan_text)
        autoscan_report.append(f"{yamldata.classic_version} | {yamldata.classic_version_date} | END OF AUTOSCAN \n")

        # CHECK IF SCAN FAILED
        stats_crashlog_scanned += 1
        if trigger_scan_failed:
            scan_failed_list.append(crashlog_file.name)

        # HIDE PERSONAL USERNAME
        user_name = user_folder.name
        user_path_1 = f"{user_folder.parent}\\{user_folder.name}"
        user_path_2 = f"{user_folder.parent}/{user_folder.name}"
        for line in autoscan_report:
            if user_name in line:
                line.replace(user_path_1, "******").replace(user_path_2, "******")

        # WRITE AUTOSCAN REPORT TO FILE
        autoscan_path = crashlog_file.with_name(crashlog_file.stem + "-AUTOSCAN.md")
        with autoscan_path.open("w", encoding="utf-8", errors="ignore") as autoscan_file:
            CMain.logger.debug(f"- - -> RUNNING CRASH LOG FILE SCAN >>> SCANNED {crashlog_file.name}")
            autoscan_output = "".join(autoscan_report)
            autoscan_file.write(autoscan_output)

        if trigger_scan_failed and move_unsolved_logs:
            backup_path = Path("CLASSIC Backup/Unsolved Logs")
            backup_path.mkdir(parents=True, exist_ok=True)
            autoscan_filepath = crashlog_file.with_name(crashlog_file.stem + "-AUTOSCAN.md")
            crash_move = backup_path / crashlog_file.name
            scan_move = backup_path / autoscan_file.name

            if crashlog_file.exists():
                shutil.copy2(crashlog_file, crash_move)
            if autoscan_filepath.exists():
                shutil.copy2(autoscan_filepath, scan_move)

    # CHECK FOR FAILED OR INVALID CRASH LOGS
    scan_invalid_list = list(Path.cwd().glob("crash-*.txt"))
    if scan_failed_list or scan_invalid_list:
        print("❌ NOTICE : CLASSIC WAS UNABLE TO PROPERLY SCAN THE FOLLOWING LOG(S):")
        print("\n".join(scan_failed_list))
        if scan_invalid_list:
            for file in scan_invalid_list:
                print(f"{file}\n")
        print("===============================================================================")
        print("Most common reason for this are logs being incomplete or in the wrong format.")
        print("Make sure that your crash log files have the .log file format, NOT .txt! \n")

    # ================================================
    # CRASH LOG SCAN COMPLETE / TERMINAL OUTPUT
    # ================================================
    crashlogs.close()
    CMain.logger.info("- - - COMPLETED CRASH LOG FILE SCAN >>> ALL AVAILABLE LOGS SCANNED")
    print("SCAN COMPLETE! (IT MIGHT TAKE SEVERAL SECONDS FOR SCAN RESULTS TO APPEAR)")
    print("SCAN RESULTS ARE AVAILABLE IN FILES NAMED crash-date-and-time-AUTOSCAN.md \n")
    print(f"{random.choice(yamldata.classic_game_hints)}\n-----")
    print(f"Scanned all available logs in {str(time.perf_counter() - 0.5 - scan_start_time)[:5]} seconds.")
    print(f"Number of Scanned Logs (No Autoscan Errors): {stats_crashlog_scanned}")
    print(f"Number of Incomplete Logs (No Plugins List): {stats_crashlog_incomplete}")
    print(f"Number of Failed Logs (Autoscan Can't Scan): {stats_crashlog_failed}\n-----")
    if CMain.gamevars["game"] == "Fallout4":
        print(yamldata.autoscan_text)
    if stats_crashlog_scanned == 0 and stats_crashlog_incomplete == 0:
        print("\n❌ CLASSIC found no crash logs to scan or the scan failed.")
        print("    There are no statistics to show (at this time).\n")


if __name__ == "__main__":
    CMain.initialize()
    from pathlib import Path

    # noinspection PyUnresolvedReferences
    from tap import Tap

    class Args(Tap):
        """Command-line arguments for CLASSIC's Command Line Interface"""

        fcx_mode: bool = False
        """Enable FCX mode"""

        show_fid_values: bool = False
        """Show FormID values"""

        stat_logging: bool = False
        """Enable statistical logging"""

        move_unsolved: bool = False
        """Move unsolved logs"""

        ini_path: Path | None = None
        """Path to the INI file"""

        scan_path: Path | None = None
        """Path to the scan directory"""

        mods_folder_path: Path | None = None
        """Path to the mods folder"""

        simplify_logs: bool = False
        """Simplify the logs"""

    args = Args().parse_args()


    if isinstance(args.fcx_mode, bool) and args.fcx_mode != CMain.classic_settings(bool, "FCX Mode"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.FCX Mode", args.fcx_mode)

    if isinstance(args.show_fid_values, bool) and args.show_fid_values != CMain.classic_settings(bool, "Show FormID Values"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "Show FormID Values", args.show_fid_values)

    if isinstance(args.move_unsolved, bool) and args.move_unsolved != CMain.classic_settings(bool, "Move Unsolved Logs"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.Move Unsolved", args.move_unsolved)

    if isinstance(args.ini_path, Path) and args.ini_path.resolve().is_dir() and str(args.ini_path) != CMain.classic_settings(str, "INI Folder Path"):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.INI Folder Path", str(args.ini_path.resolve()))

    if isinstance(args.scan_path, Path) and args.scan_path.resolve().is_dir() and str(args.scan_path) != CMain.classic_settings(str, "SCAN Custom Path"):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.SCAN Custom Path", str(args.scan_path.resolve()))

    if (
        isinstance(args.mods_folder_path, Path)
        and args.mods_folder_path.resolve().is_dir()
        and str(args.mods_folder_path) != CMain.classic_settings(str, "MODS Folder Path")
    ):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.MODS Folder Path", str(args.mods_folder_path.resolve()))

    if isinstance(args.simplify_logs, bool) and args.simplify_logs != CMain.classic_settings(bool, "Simplify Logs"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.Simplify Logs", args.simplify_logs)

    crashlogs_scan()
    os.system("pause")
