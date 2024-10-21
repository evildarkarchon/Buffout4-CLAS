import os
import random
import shutil
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import regex as re
import requests

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
    # CLASSIC_pastebin = CLASSIC_logs / "Pastebin"
    CUSTOM_folder_setting = CMain.classic_settings(str, "SCAN Custom Path")
    XSE_folder_setting = CMain.yaml_settings(str, CMain.YAML.Game_Local, "Game_Info.Docs_Folder_XSE")

    CUSTOM_folder = Path(CUSTOM_folder_setting) if isinstance(CUSTOM_folder_setting, str) else None
    XSE_folder = Path(XSE_folder_setting) if isinstance(XSE_folder_setting, str) else None

    if not CLASSIC_logs.is_dir():
        CLASSIC_logs.mkdir(parents=True, exist_ok=True)
    # if not CLASSIC_pastebin.is_dir():
    #     CLASSIC_pastebin.mkdir(parents=True, exist_ok=True)
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

    crash_files = list(CLASSIC_logs.glob("crash-*.log"))
    # crash_files.extend(list(CLASSIC_pastebin.glob("crash-*.log")))
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
    for mod_name in yaml_dict:
        mod_name_lower = mod_name.lower()
        mod_warn = yaml_dict.get(mod_name)
        for plugin_name, plugin_fid in crashlog_plugins.items():
            if mod_name_lower in plugin_name.lower():
                if mod_warn:
                    autoscan_report.extend((f"[!] FOUND : [{plugin_fid}] ", mod_warn))
                else:
                    raise ValueError(f"ERROR: {mod_name} has no warning in the database!")
                trigger_mod_found = True
                break
    return trigger_mod_found


def detect_mods_double(yaml_dict: dict[str, str], crashlog_plugins: dict[str, str], autoscan_report: list[str]) -> bool:
    """Detect one split key (2 mods) per loop in YAML dict."""
    trigger_mod_found = False
    for mod_name in yaml_dict:
        mod_warn = yaml_dict.get(mod_name)
        mod_split = mod_name.lower().split(" | ", 1)
        mod1_found = mod2_found = False
        for plugin_name in crashlog_plugins:
            plugin_name = plugin_name.lower()
            if not mod1_found and mod_split[0] in plugin_name:
                mod1_found = True
                continue
            if not mod2_found and mod_split[1] in plugin_name:
                mod2_found = True
                continue
        if mod1_found and mod2_found:
            if mod_warn:
                autoscan_report.extend(("[!] CAUTION : ", mod_warn))
            else:
                raise ValueError(f"ERROR: {mod_name} has no warning in the database!")
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
def find_segments(crash_data: list[str], xse_acronym: str) -> list[list[str]]:
    """Divide the log up into segments."""
    xse = xse_acronym.upper()
    segment_boundaries = (
        ("	[Compatibility]", "SYSTEM SPECS:"),
        ("SYSTEM SPECS:", "PROBABLE CALL STACK:"),
        ("PROBABLE CALL STACK:", "MODULES:"),
        ("MODULES:", f"{xse} PLUGINS:"),
        (f"{xse} PLUGINS:", "PLUGINS:"),
        ("PLUGINS:", "EOF"),
    )
    segment_index = 0
    collect = False
    segments: list[list[str]] = []
    next_boundary = segment_boundaries[0][0]
    index_start = 0
    total = len(crash_data)
    current_index = 0
    while current_index < total:
        line = crash_data[current_index]
        if line.startswith(next_boundary):
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

    missing_segments = len(segment_boundaries) - len(segments)
    if missing_segments > 0:
        segments.extend([[]] * missing_segments)
    return [[line.strip() for line in segment] for segment in segments]


# ================================================
# CRASH LOG SCAN START
# ================================================
def crashlogs_scan() -> None:
    pluginsearch = re.compile(r"\s*\[(FE:([0-9A-F]{3})|[0-9A-F]{2})\]\s*(.+?(?:\.es[pml])+)", flags=re.IGNORECASE)
    # is_ng_log = re.compile(r"\s*\[([0-9A-F]{2})\]([^\s]+.*)", flags=re.IGNORECASE)
    crashlog_list = crashlogs_get_files()
    print("REFORMATTING CRASH LOGS, PLEASE WAIT...\n")
    remove_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_records") or []
    crashlogs_reformat(crashlog_list, remove_list)

    print("SCANNING CRASH LOGS, PLEASE WAIT...\n")
    scan_start_time = time.perf_counter()
    # ================================================
    # Grabbing YAML values is time expensive, so keep these out of the main file loop.
    classic_game_hints = CMain.yaml_settings(list[str], CMain.YAML.Game, "Game_Hints") or []
    classic_records_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "catch_log_records") or []
    classic_version = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version") or ""
    classic_version_date = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version_date") or ""

    crashgen_name = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LogName") or ""
    crashgen_latest_og = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LatestVer") or ""
    crashgen_latest_vr = CMain.yaml_settings(str, CMain.YAML.Game, "GameVR_Info.CRASHGEN_LatestVer") or ""
    crashgen_ignore = CMain.yaml_settings(list[str], CMain.YAML.Game, f"Game{CMain.gamevars["vr"]}_Info.CRASHGEN_Ignore") or []

    warn_noplugins = CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_NOPlugins") or ""
    warn_outdated = CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_Outdated") or ""
    xse_acronym = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.XSE_Acronym") or ""

    game_ignore_plugins = CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Plugins_Exclude") or []
    game_ignore_records = CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Records_Exclude") or []
    suspects_error_list = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Crashlog_Error_Check") or {}
    suspects_stack_list = CMain.yaml_settings(dict[str, list[str]], CMain.YAML.Game, "Crashlog_Stack_Check") or {}

    autoscan_text = CMain.yaml_settings(str, CMain.YAML.Main, f"CLASSIC_Interface.autoscan_text_{CMain.gamevars["game"]}") or ""
    ignore_list = CMain.yaml_settings(list[str], CMain.YAML.Ignore, f"CLASSIC_Ignore_{CMain.gamevars["game"]}") or []

    game_mods_conf = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CONF") or {}
    game_mods_core = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE") or {}
    games_mods_core_folon = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE_FOLON") or {}
    game_mods_freq = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_FREQ") or {}
    game_mods_opc2 = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_OPC2") or {}
    game_mods_solu = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_SOLU") or {}

    xse_acronym = xse_acronym.lower()
    fcx_mode = CMain.classic_settings(bool, "FCX Mode")
    show_formid_values = CMain.classic_settings(bool, "Show FormID Values")
    formid_db_exists = any(db.is_file() for db in DB_PATHS)
    move_unsolved_logs = CMain.classic_settings(bool, "Move Unsolved Logs")
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
    for crashlog_file in crashlog_list:
        autoscan_report: list[str] = []
        trigger_plugin_limit = trigger_plugins_loaded = trigger_scan_failed = False
        with crashlog_file.open(encoding="utf-8", errors="ignore") as crash_log:
            crash_log.seek(0)  # DON'T FORGET WHEN READING FILE MULTIPLE TIMES
            crash_data = crash_log.readlines()

        autoscan_report.extend((
            f"{crashlog_file.name} -> AUTOSCAN REPORT GENERATED BY {classic_version} \n",
            "# FOR BEST VIEWING EXPERIENCE OPEN THIS FILE IN NOTEPAD++ OR SIMILAR # \n",
            "# PLEASE READ EVERYTHING CAREFULLY AND BEWARE OF FALSE POSITIVES # \n",
            "====================================================\n",
        ))

        # ================================================
        # 1) CHECK EXISTENCE AND INDEXES OF EACH SEGMENT
        # ================================================

        # Set default index values incase actual index is not found.
        try:
            index_crashgenver = next(
                index for index, item in enumerate(crash_data) if index < 10 and crashgen_name and crashgen_name.lower() in item.lower()
            )
        except StopIteration:
            index_crashgenver = 1
        try:
            index_mainerror = next(index for index, item in enumerate(crash_data) if index < 10 and "unhandled exception" in item.lower())
        except StopIteration:
            index_mainerror = 3

        # ================================================
        # 2) GENERATE REQUIRED SEGMENTS FROM THE CRASH LOG
        # ================================================
        segment_crashgen, segment_system, segment_callstack, segment_allmodules, segment_xsemodules, segment_plugins = find_segments(crash_data, xse_acronym)
        segment_callstack_intact = "".join(segment_callstack)
        if not segment_plugins:
            stats_crashlog_incomplete += 1
        if len(crash_data) < 20:
            stats_crashlog_scanned -= 1
            stats_crashlog_failed += 1
            trigger_scan_failed = True

        # ================== MAIN ERROR ==================
        crashlog_mainerror = crash_data[index_mainerror] if len(crash_data) > index_mainerror else "UNKNOWN"
        autoscan_report.append(f"\nMain Error: {crashlog_mainerror.replace("|", "\n", 1)}\n")

        # =============== CRASHGEN VERSION ===============
        crashlog_crashgen = crash_data[index_crashgenver].strip()
        autoscan_report.append(f"Detected {crashgen_name} Version: {crashlog_crashgen} \n")
        if crashlog_crashgen in {crashgen_latest_og, crashgen_latest_vr}:
            autoscan_report.append(f"* You have the latest version of {crashgen_name}! *\n\n")
        else:
            autoscan_report.append(f"{warn_outdated} \n")

        # ======= REQUIRED LISTS, DICTS AND CHECKS =======
        ignore_plugins_list = [item.lower() for item in ignore_list] if ignore_list else []

        crashlog_plugins: dict[str, str] = {}

        esm_name = f"{CMain.gamevars["game"]}.esm"
        if any(esm_name in elem for elem in segment_plugins):
            trigger_plugins_loaded = True
        else:
            stats_crashlog_incomplete += 1

        # ================================================
        # 3) CHECK EACH SEGMENT AND CREATE REQUIRED VALUES
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
                    trigger_plugin_limit = True
                pluginmatch = pluginsearch.match(elem, concurrent=True)
                if pluginmatch is not None:
                    # if ng_log_match and ng_log_match.group(1) and ng_log_match.group(2):
                    #     plugin_fid = pluginmatch.group(2)
                    # else:
                    #     plugin_fid = pluginmatch.group(1)
                    plugin_fid = pluginmatch.group(1)
                    plugin_name = pluginmatch.group(3)
                    if plugin_fid is not None and all(plugin_name not in item for item in crashlog_plugins):
                        crashlog_plugins[plugin_name] = plugin_fid.replace(":", "")
                    elif plugin_name and "dll" in plugin_name.lower():
                        crashlog_plugins[plugin_name] = "DLL"
                    else:
                        crashlog_plugins[plugin_name] = "???"

                # if " " in elem:
                #     elem = elem.replace("     ", " ").strip()
                #     elem_parts = elem.split(" ", 1)
                #     elem_parts[0] = elem_parts[0].replace("[", "").replace(":", "").replace("]", "")
                #     crashlog_plugins[elem_parts[1]] = elem_parts[0]

        for elem in segment_xsemodules:
            # SOME IMPORTANT DLLs HAVE A VERSION, REMOVE IT
            elem = elem.strip()
            if ".dll v" in elem:
                elem_parts = elem.split(" v", 1)
                elem = elem_parts[0]
            if all(elem not in item for item in crashlog_plugins):
                crashlog_plugins[elem] = "DLL"

        for elem in segment_allmodules:
            # SOME IMPORTANT DLLs ONLY APPEAR UNDER ALL MODULES
            if "vulkan" in elem.lower():
                elem_parts = elem.strip().split(" ", 1)
                elem_parts[1] = "DLL"
                if all(elem_parts[0] not in item for item in crashlog_plugins):
                    crashlog_plugins[elem_parts[0]] = elem_parts[1]

        # CHECK IF THERE ARE ANY PLUGINS IN THE IGNORE YAML
        if ignore_plugins_list:
            for item in ignore_plugins_list:
                if any(item.lower() == plugin.lower() for plugin in crashlog_plugins):
                    del crashlog_plugins[item]

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
        for error in suspects_error_list:
            error_split_0, error_split_1 = error.split(" | ", 1)
            if error_split_1 in crashlog_mainerror:
                error_split_1 = error_split_1.ljust(max_warn_length, ".")
                autoscan_report.append(f"# Checking for {error_split_1} SUSPECT FOUND! > Severity : {error_split_0} # \n-----\n")
                trigger_suspect_found = True

        for key in suspects_stack_list:
            key_split_0, key_split_1 = key.split(" | ", 1)
            error_req_found = error_opt_found = stack_found = False
            item_list = suspects_stack_list.get(key, [])
            has_required_item = any("ME-REQ|" in elem for elem in item_list)
            for item in item_list:
                if "|" in item:
                    item_split_0, item_split_1 = item.split("|", 1)
                    if item_split_0 == "ME-REQ":
                        if item_split_1 in crashlog_mainerror:
                            error_req_found = True
                    elif item_split_0 == "ME-OPT":
                        if item_split_1 in crashlog_mainerror:
                            error_opt_found = True
                    elif item_split_0.isdecimal():
                        if segment_callstack_intact.count(item_split_1) >= int(item_split_0):
                            stack_found = True
                    elif item_split_0 == "NOT" and item_split_1 in segment_callstack_intact:
                        break
                elif item in segment_callstack_intact:
                    stack_found = True

            # print(f"TEST: {error_req_found} | {error_opt_found} | {stack_found}")
            if has_required_item:
                if error_req_found:
                    key_split_1 = key_split_1.ljust(max_warn_length, ".")
                    autoscan_report.append(f"# Checking for {key_split_1} SUSPECT FOUND! > Severity : {key_split_0} # \n-----\n")
                    trigger_suspect_found = True
            elif error_opt_found or stack_found:
                key_split_1 = key_split_1.ljust(max_warn_length, ".")
                autoscan_report.append(f"# Checking for {key_split_1} SUSPECT FOUND! > Severity : {key_split_0} # \n-----\n")
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

        Has_XCell = any("x-cell-fo4.dll" in elem.lower() for elem in segment_xsemodules)
        Has_BakaScrapHeap = any("bakascrapheap.dll" in elem.lower() for elem in segment_xsemodules)

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
                crashgen_ignore.extend(("havokmemorysystem", "scaleformallocator", "smallblockallocator"))
            for line in segment_crashgen:
                line_lower = line.lower()
                if "false" in line_lower and all(elem.lower() not in line_lower for elem in crashgen_ignore):
                    autoscan_report.append(
                        f"* NOTICE : {line.split(":", 1)[0].strip()} is disabled in your {crashgen_name} settings, is this intentional? * \n-----\n",
                    )

                if "achievements:" in line_lower:
                    if "true" in line_lower and any(
                        any(dll in elem.lower() for dll in ("achievements.dll", "unlimitedsurvivalmode.dll")) for elem in segment_xsemodules
                    ):
                        autoscan_report.extend((
                            "# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE # \n",
                            f" FIX: Open {crashgen_name}'s TOML file and change Achievements to FALSE, this prevents conflicts with {crashgen_name}.\n-----\n",
                        ))
                    else:
                        autoscan_report.append(
                            f"✔️ Achievements parameter is correctly configured in your {crashgen_name} settings! \n-----\n",
                        )

                if "memorymanager:" in line_lower:
                    if Has_BakaScrapHeap and not Has_XCell and "true" in line_lower:
                        autoscan_report.extend((
                            "# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but MemoryManager parameter is set to TRUE # \n",
                            f" FIX: Open {crashgen_name}'s TOML file and change MemoryManager to FALSE, this prevents conflicts with {crashgen_name}.\n-----\n",
                        ))
                    elif Has_XCell and not Has_BakaScrapHeap and "true" in line_lower:
                        autoscan_report.extend((
                            "# ❌ CAUTION : X-Cell is installed, but MemoryManager parameter is set to TRUE # \n",
                            f" FIX: Open {crashgen_name}'s TOML file and change MemoryManager to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                        ))
                    elif Has_XCell and not Has_BakaScrapHeap and "false" in line_lower:
                        autoscan_report.append(
                            f"✔️ Memory Manager parameter is correctly configured for use with X-Cell in your {crashgen_name} settings! \n-----\n",
                        )
                    else:
                        autoscan_report.append(
                            f"✔️ Memory Manager parameter is correctly configured in your {crashgen_name} settings! \n-----\n",
                        )

                if Has_XCell:
                    if "bstexturestreamerlocalheap:" in line_lower:
                        if "true" in line_lower:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but BSTextureStreamerLocalHeap parameter is set to TRUE # \n",
                                f" FIX: Open {crashgen_name}'s TOML file and change BSTextureStreamerLocalHeap to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        elif "false" in line_lower:
                            autoscan_report.append(
                                f"✔️ BSTextureStreamerLocalHeap parameter is correctly configured for use with X-Cell in your {crashgen_name} settings! \n-----\n",
                            )

                    if "havokmemorysystem:" in line_lower:
                        if "true" in line_lower:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but HavokMemorySystem parameter is set to TRUE # \n",
                                f" FIX: Open {crashgen_name}'s TOML file and change HavokMemorySystem to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        elif "false" in line_lower:
                            autoscan_report.append(
                                f"✔️ HavokMemorySystem parameter is correctly configured for use with X-Cell in your {crashgen_name} settings! \n-----\n",
                            )

                    if "scaleformallocator:" in line_lower:
                        if "true" in line_lower:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but ScaleformAllocator parameter is set to TRUE # \n",
                                f" FIX: Open {crashgen_name}'s TOML file and change ScaleformAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        elif "false" in line_lower:
                            autoscan_report.append(
                                f"✔️ ScaleformAllocator parameter is correctly configured for use with X-Cell in your {crashgen_name} settings! \n-----\n",
                            )

                    if "smallblockallocator:" in line_lower:
                        if "true" in line_lower:
                            autoscan_report.extend((
                                "# ❌ CAUTION : X-Cell is installed, but SmallBlockAllocator parameter is set to TRUE # \n",
                                f" FIX: Open {crashgen_name}'s TOML file and change SmallBlockAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n",
                            ))
                        elif "false" in line_lower:
                            autoscan_report.append(
                                f"✔️ SmallBlockAllocator parameter is correctly configured for use with X-Cell in your {crashgen_name} settings! \n-----\n",
                            )

                if "f4ee:" in line_lower:
                    if "false" in line_lower and any("f4ee.dll" in elem.lower() for elem in segment_xsemodules):
                        autoscan_report.extend((
                            "# ❌ CAUTION : Looks Menu is installed, but F4EE parameter under [Compatibility] is set to FALSE # \n",
                            f" FIX: Open {crashgen_name}'s TOML file and change F4EE to TRUE, this prevents bugs and crashes from Looks Menu.\n-----\n",
                        ))
                    else:
                        autoscan_report.append(
                            f"✔️ F4EE (Looks Menu) parameter is correctly configured in your {crashgen_name} settings! \n-----\n",
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
            if detect_mods_single(game_mods_freq, crashlog_plugins, autoscan_report):
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
            autoscan_report.append(warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING FOR MODS THAT CONFLICT WITH OTHER MODS...\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if detect_mods_double(game_mods_conf, crashlog_plugins, autoscan_report):
                autoscan_report.extend((
                    "# [!] CAUTION : FOUND MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n",
                    "* YOU SHOULD CHOOSE WHICH MOD TO KEEP AND DISABLE OR COMPLETELY REMOVE THE OTHER MOD * \n\n",
                ))
            else:
                autoscan_report.append("# FOUND NO MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n\n")
        else:
            autoscan_report.append(warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING FOR MODS WITH SOLUTIONS & COMMUNITY PATCHES\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if detect_mods_single(game_mods_solu, crashlog_plugins, autoscan_report):
                autoscan_report.extend((
                    "# [!] CAUTION : FOUND PROBLEMATIC MODS WITH SOLUTIONS AND COMMUNITY PATCHES # \n",
                    "[Due to limitations, CLASSIC will show warnings for some mods even if fixes or patches are already installed.] \n",
                    "[To hide these warnings, you can add their plugin names to the CLASSIC Ignore.yaml file. ONE PLUGIN PER LINE.] \n\n",
                ))
            else:
                autoscan_report.append(
                    "# FOUND NO PROBLEMATIC MODS WITH AVAILABLE SOLUTIONS AND COMMUNITY PATCHES # \n\n",
                )
        else:
            autoscan_report.append(warn_noplugins)

        if CMain.gamevars["game"] == "Fallout4":
            autoscan_report.extend((
                "====================================================\n",
                "CHECKING FOR MODS PATCHED THROUGH OPC INSTALLER...\n",
                "====================================================\n",
            ))

            if trigger_plugins_loaded:
                if detect_mods_single(game_mods_opc2, crashlog_plugins, autoscan_report):
                    autoscan_report.extend((
                        "\n* FOR PATCH REPOSITORY THAT PREVENTS CRASHES AND FIXES PROBLEMS IN THESE AND OTHER MODS,* \n",
                        "* VISIT OPTIMIZATION PATCHES COLLECTION: https://www.nexusmods.com/fallout4/mods/54872 * \n\n",
                    ))
                else:
                    autoscan_report.append(
                        "# FOUND NO PROBLEMATIC MODS THAT ARE ALREADY PATCHED THROUGH THE OPC INSTALLER # \n\n",
                    )
            else:
                autoscan_report.append(warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "CHECKING IF IMPORTANT PATCHES & FIXES ARE INSTALLED\n",
            "====================================================\n",
        ))

        if trigger_plugins_loaded:
            if any("londonworldspace" in plugin.lower() for plugin in crashlog_plugins):
                detect_mods_important(games_mods_core_folon, crashlog_plugins, autoscan_report, gpu_rival)
            else:
                detect_mods_important(game_mods_core, crashlog_plugins, autoscan_report, gpu_rival)
        else:
            autoscan_report.append(warn_noplugins)

        autoscan_report.extend((
            "====================================================\n",
            "SCANNING THE LOG FOR SPECIFIC (POSSIBLE) SUSPECTS...\n",
            "====================================================\n",
        ))

        if trigger_plugin_limit:
            warn_plugin_limit = CMain.yaml_settings(str, CMain.YAML.Main, "Mods_Warn.Mods_Plugin_Limit") or ""
            autoscan_report.append(warn_plugin_limit)

        # ================================================

        autoscan_report.append("# LIST OF (POSSIBLE) PLUGIN SUSPECTS #\n")
        plugins_matches: list[str] = []
        for line in segment_callstack:
            line = line.lower()
            for plugin in crashlog_plugins:
                plugin = plugin.lower()
                if plugin in line and "modified by:" not in line and all(ignore.lower() not in plugin for ignore in game_ignore_plugins):
                    plugins_matches.append(plugin)

        if plugins_matches:
            plugins_found = dict(Counter(plugins_matches))
            if plugins_found:
                autoscan_report.extend([f"- {key} | {value}\n" for key, value in plugins_found.items()])
                autoscan_report.extend((
                    "\n[Last number counts how many times each Plugin Suspect shows up in the crash log.]\n",
                    f"These Plugins were caught by {crashgen_name} and some of them might be responsible for this crash.\n",
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
                f"These Form IDs were caught by {crashgen_name} and some of them might be related to this crash.\n",
                "You can try searching any listed Form IDs in xEdit and see if they lead to relevant records.\n\n",
            ))
        else:
            autoscan_report.append("* COULDN'T FIND ANY FORM ID SUSPECTS *\n\n")

        # ================================================

        autoscan_report.append("# LIST OF DETECTED (NAMED) RECORDS #\n")
        records_matches: list[str] = []
        for line in segment_callstack:
            if any(item.lower() in line.lower() for item in classic_records_list) and all(
                record.lower() not in line.lower() for record in game_ignore_records
            ):
                if "[RSP+" in line:
                    line = line[30:].strip()
                    records_matches.append(line)
                else:
                    records_matches.append(line.strip())
        if records_matches:
            records_found = dict(Counter(sorted(records_matches)))
            for record, count in records_found.items():
                autoscan_report.append(f"- {record} | {count}\n")

            autoscan_report.extend((
                "\n[Last number counts how many times each Named Record shows up in the crash log.]\n",
                f"These records were caught by {crashgen_name} and some of them might be related to this crash.\n",
                "Named records should give extra info on involved game objects, record types or mod files.\n\n",
            ))
        else:
            autoscan_report.append("* COULDN'T FIND ANY NAMED RECORDS *\n\n")

        # ============== AUTOSCAN REPORT END ==============
        if CMain.gamevars["game"] == "Fallout4":
            autoscan_report.append(autoscan_text)
        autoscan_report.append(f"{classic_version} | {classic_version_date} | END OF AUTOSCAN \n")

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
    CMain.logger.info("- - - COMPLETED CRASH LOG FILE SCAN >>> ALL AVAILABLE LOGS SCANNED")
    print("SCAN COMPLETE! (IT MIGHT TAKE SEVERAL SECONDS FOR SCAN RESULTS TO APPEAR)")
    print("SCAN RESULTS ARE AVAILABLE IN FILES NAMED crash-date-and-time-AUTOSCAN.md \n")
    print(f"{random.choice(classic_game_hints)}\n-----")
    print(f"Scanned all available logs in {str(time.perf_counter() - 0.5 - scan_start_time)[:5]} seconds.")
    print(f"Number of Scanned Logs (No Autoscan Errors): {stats_crashlog_scanned}")
    print(f"Number of Incomplete Logs (No Plugins List): {stats_crashlog_incomplete}")
    print(f"Number of Failed Logs (Autoscan Can't Scan): {stats_crashlog_failed}\n-----")
    if CMain.gamevars["game"] == "Fallout4":
        print(autoscan_text)
    if stats_crashlog_scanned == 0 and stats_crashlog_incomplete == 0:
        print("\n❌ CLASSIC found no crash logs to scan or the scan failed.")
        print("    There are no statistics to show (at this time).\n")


if __name__ == "__main__":
    CMain.initialize()
    import argparse

    parser = argparse.ArgumentParser(
        prog="Crash Log Auto Scanner & Setup Integrity Checker (CLASSIC)",
        description="All terminal options are saved to the YAML file.",
    )
    # Argument values will simply change INI values since that requires the least refactoring
    # I will figure out a better way in a future iteration, this iteration simply mimics the GUI. - evildarkarchon
    parser.add_argument("--fcx-mode", action=argparse.BooleanOptionalAction, help="Enable (or disable) FCX mode")
    parser.add_argument("--show-fid-values", action=argparse.BooleanOptionalAction, help="Enable (or disable) IMI mode")
    parser.add_argument("--stat-logging", action=argparse.BooleanOptionalAction, help="Enable (or disable) Stat Logging")
    parser.add_argument(
        "--move-unsolved",
        action=argparse.BooleanOptionalAction,
        help="Enable (or disable) moving unsolved logs to a separate directory",
    )
    parser.add_argument("--ini-path", type=Path, help="Set the directory that stores the game's INI files.")
    parser.add_argument("--scan-path", type=Path, help="Set which custom directory to scan crash logs from.")
    parser.add_argument("--mods-folder-path", type=Path, help="Set the directory where your mod manager stores your mods (Optional).")
    parser.add_argument("--simplify-logs", action=argparse.BooleanOptionalAction, help="Enable (or disable) Simplify Logs")
    args = parser.parse_args()

    # VSCode gives type errors because args.* is set at runtime (doesn't know what types it's dealing with).
    # Using intermediate variables with type annotations to satisfy it.
    # TODO: Implement Typed Argument Parser or similar
    scan_path: Path = args.scan_path
    ini_path: Path = args.ini_path
    mods_folder_path: Path = args.mods_folder_path

    # Default output value for an argparse.BooleanOptionalAction is None, and so fails the isinstance check.
    # So it will respect current INI values if not specified on the command line.
    if isinstance(args.fcx_mode, bool) and args.fcx_mode != CMain.classic_settings(bool, "FCX Mode"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.FCX Mode", args.fcx_mode)

    if isinstance(args.show_fid_values, bool) and args.show_fid_values != CMain.classic_settings(bool, "Show FormID Values"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.IMI Mode", args.imi_mode)

    if isinstance(args.move_unsolved, bool) and args.move_unsolved != CMain.classic_settings(bool, "Move Unsolved Logs"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.Move Unsolved", args.args.move_unsolved)

    if isinstance(ini_path, Path) and ini_path.resolve().is_dir() and str(ini_path) != CMain.classic_settings(str, "INI Folder Path"):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.INI Folder Path", str(ini_path.resolve()))

    if isinstance(scan_path, Path) and scan_path.resolve().is_dir() and str(scan_path) != CMain.classic_settings(str, "SCAN Custom Path"):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.SCAN Custom Path", str(scan_path.resolve()))

    if (
        isinstance(mods_folder_path, Path)
        and mods_folder_path.resolve().is_dir()
        and str(mods_folder_path) != CMain.classic_settings(str, "MODS Folder Path")
    ):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.MODS Folder Path", str(mods_folder_path.resolve()))

    if isinstance(args.simplify_logs, bool) and args.simplify_logs != CMain.classic_settings(bool, "Simplify Logs"):
        CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.Simplify Logs", args.simplify_logs)

    crashlogs_scan()
    os.system("pause")
