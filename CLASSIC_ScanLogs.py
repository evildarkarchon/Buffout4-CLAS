import os
import random
import shutil
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import regex as re
import requests
from packaging.version import Version

import CLASSIC_Main as CMain
import CLASSIC_ScanGame as CGame

type Plugin = tuple[str, str]
type PluginDict = dict[str, str]

query_cache: dict[tuple[str, str], str] = {}
# Define paths for both Main and Local databases
DB_PATHS = (
    Path(f"CLASSIC Data/databases/{CMain.gamevars['game']} FormIDs Main.db"),
    Path(f"CLASSIC Data/databases/{CMain.gamevars['game']} FormIDs Local.db"),
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
    outfile = pastebin_path / f"crash-{urlparse(url).path.split('/')[-1]}.log"
    outfile.write_text(response.text, encoding="utf-8", errors="ignore")


def get_entry(formid: str, plugin: str) -> str | None:
    if (entry := query_cache.get((formid, plugin))) is not None:
        return entry

    for db_path in DB_PATHS:
        if db_path.is_file():
            with sqlite3.connect(db_path) as conn:
                c = conn.cursor()
                c.execute(
                    f"SELECT entry FROM {CMain.gamevars['game']} WHERE formid=? AND plugin=? COLLATE nocase",
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
                crash_data[reversed_index] = f"{indent}[{fid.replace(' ', '0')}]{name}"

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
    game_root_name = CMain.yaml_settings(str, CMain.YAML.Game, f"Game_{CMain.gamevars['vr']}Info.Main_Root_Name")
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
        self.classic_version = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version") or ""
        self.classic_version_date = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version_date") or ""
        self.crashgen_name = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LogName") or ""
        self.crashgen_latest_og = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.CRASHGEN_LatestVer") or ""
        self.crashgen_latest_vr = CMain.yaml_settings(str, CMain.YAML.Game, "GameVR_Info.CRASHGEN_LatestVer") or ""
        self.crashgen_ignore = set(
            CMain.yaml_settings(list[str], CMain.YAML.Game, f"Game{CMain.gamevars['vr']}_Info.CRASHGEN_Ignore") or []
        )
        self.warn_noplugins = CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_NOPlugins") or ""
        self.warn_outdated = CMain.yaml_settings(str, CMain.YAML.Game, "Warnings_CRASHGEN.Warn_Outdated") or ""
        self.xse_acronym = CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.XSE_Acronym") or ""
        self.game_ignore_plugins = CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Plugins_Exclude") or []
        self.game_ignore_records = CMain.yaml_settings(list[str], CMain.YAML.Game, "Crashlog_Records_Exclude") or []
        self.suspects_error_list = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Crashlog_Error_Check") or {}
        self.suspects_stack_list = CMain.yaml_settings(dict[str, list[str]], CMain.YAML.Game, "Crashlog_Stack_Check") or {}
        self.autoscan_text = CMain.yaml_settings(str, CMain.YAML.Main, f"CLASSIC_Interface.autoscan_text_{CMain.gamevars['game']}") or ""
        self.ignore_list = CMain.yaml_settings(list[str], CMain.YAML.Ignore, f"CLASSIC_Ignore_{CMain.gamevars['game']}") or []
        self.game_mods_conf = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CONF") or {}
        self.game_mods_core = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE") or {}
        self.game_mods_core_folon = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_CORE_FOLON") or {}
        self.game_mods_freq = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_FREQ") or {}
        self.game_mods_opc2 = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_OPC2") or {}
        self.game_mods_solu = CMain.yaml_settings(dict[str, str], CMain.YAML.Game, "Mods_SOLU") or {}
        self.game_version = Version(CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.GameVersion") or "0.0.0")
        self.game_version_new = Version(CMain.yaml_settings(str, CMain.YAML.Game, "Game_Info.GameVersionNEW") or "0.0.0")
        self.game_version_vr = Version(CMain.yaml_settings(str, CMain.YAML.Game, "GameVR_Info.GameVersion") or "0.0.0")


# ================================================
# CRASH LOG SCAN START
# ================================================
@dataclass
class CrashLogSegments:
    """Container for the different segments of a crash log."""

    crashgen: list[str]
    system: list[str]
    callstack: list[str]
    allmodules: list[str]
    xsemodules: list[str]
    plugins: list[str]
    callstack_intact: str
    gameversion: str
    crashgen_version: str
    mainerror: str

    @property
    def xsemodules_lower(self) -> set[str]:
        """Get lowercase XSE module names with version numbers removed."""
        return {x.split(" v", 1)[0].strip() if "dll v" in x else x.strip() for x in (module.lower() for module in self.xsemodules)}


def read_crash_log(crash_file: Path) -> list[str]:
    """Read and return lines from crash log file."""
    crashlogs = SQLiteReader([crash_file])
    crash_data = crashlogs.read_log(crash_file.name)
    crashlogs.close()
    return crash_data


def parse_crash_log_segments(crash_data: list[str], xse_acronym: str, crashgen_name: str) -> CrashLogSegments:
    """Parse crash log into segments."""
    gameversion, crashgen, mainerror, segments = find_segments(crash_data, xse_acronym, crashgen_name)

    if len(segments) < 6:
        # If we don't have all segments, return empty segments
        segments = [[] for _ in range(6)]

    return CrashLogSegments(
        crashgen=segments[0],
        system=segments[1],
        callstack=segments[2],
        allmodules=segments[3],
        xsemodules=segments[4],
        plugins=segments[5],
        callstack_intact="".join(segments[2]),
        gameversion=gameversion,
        crashgen_version=crashgen,
        mainerror=mainerror,
    )


def process_crashgen_settings(
    crashgen: dict[str, Any], yamldata: ClassicScanLogsInfo, xsemodules: set[str], autoscan_report: list[str]
) -> None:
    Has_XCell = "x-cell-fo4.dll" in xsemodules
    Has_BakaScrapHeap = "bakascrapheap.dll" in xsemodules
    """Process crashgen settings and report any issues."""

    # Check Achievements setting
    crashgen_achievements = crashgen.get("Achievements")
    if crashgen_achievements is not None:
        if crashgen_achievements and ("achievements.dll" in xsemodules or "unlimitedsurvivalmode.dll" in xsemodules):
            autoscan_report.extend((
                "# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE # \n",
                f" FIX: Open {yamldata.crashgen_name}'s TOML file and change Achievements to FALSE, this prevents conflicts with {yamldata.crashgen_name}.\n-----\n",
            ))
        else:
            autoscan_report.append(f"✔️ Achievements parameter is correctly configured in your {yamldata.crashgen_name} settings! \n-----\n")

    # Check MemoryManager setting
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

    # Process X-Cell specific settings
    if Has_XCell:
        # Check HavokMemorySystem
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

        # Check BSTextureStreamerLocalHeap
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

        # Check ScaleformAllocator
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

        # Check SmallBlockAllocator
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

    # Check F4EE compatibility
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


def write_autoscan_report(crashlog_file: Path, autoscan_report: list[str]) -> None:
    """Write the autoscan report to a file."""
    # Replace personal username in paths if present
    user_folder = Path.home()
    user_name = user_folder.name
    user_path_1 = f"{user_folder.parent}\\{user_folder.name}"
    user_path_2 = f"{user_folder.parent}/{user_folder.name}"

    sanitized_report = []
    for line in autoscan_report:
        if user_name in line:
            line = line.replace(user_path_1, "******").replace(user_path_2, "******")
        sanitized_report.append(line)

    # Write report to file
    autoscan_path = crashlog_file.with_name(crashlog_file.stem + "-AUTOSCAN.md")
    with autoscan_path.open("w", encoding="utf-8", errors="ignore") as autoscan_file:
        CMain.logger.debug(f"- - -> RUNNING CRASH LOG FILE SCAN >>> SCANNED {crashlog_file.name}")
        autoscan_file.write("".join(sanitized_report))


def move_unsolved_logs(crashlog_file: Path) -> None:
    """Move unsolved logs to backup folder."""
    backup_path = Path("CLASSIC Backup/Unsolved Logs")
    backup_path.mkdir(parents=True, exist_ok=True)

    # Move both crash log and its autoscan report
    autoscan_filepath = crashlog_file.with_name(crashlog_file.stem + "-AUTOSCAN.md")
    crash_move = backup_path / crashlog_file.name
    scan_move = backup_path / autoscan_filepath.name

    if crashlog_file.exists():
        shutil.copy2(crashlog_file, crash_move)
    if autoscan_filepath.exists():
        shutil.copy2(autoscan_filepath, scan_move)


def print_final_stats(stats: dict[str, int], scan_start_time: float, scan_failed_list: list[str], yamldata: ClassicScanLogsInfo) -> None:
    """Print final statistics and information."""
    CMain.logger.info("- - - COMPLETED CRASH LOG FILE SCAN >>> ALL AVAILABLE LOGS SCANNED")

    print("SCAN COMPLETE! (IT MIGHT TAKE SEVERAL SECONDS FOR SCAN RESULTS TO APPEAR)")
    print("SCAN RESULTS ARE AVAILABLE IN FILES NAMED crash-date-and-time-AUTOSCAN.md \n")

    # Print random hint
    print(f"{random.choice(yamldata.classic_game_hints)}\n-----")

    # Print statistics
    print(f"Scanned all available logs in {str(time.perf_counter() - 0.5 - scan_start_time)[:5]} seconds.")
    print(f"Number of Scanned Logs (No Autoscan Errors): {stats['scanned']}")
    print(f"Number of Incomplete Logs (No Plugins List): {stats['incomplete']}")
    print(f"Number of Failed Logs (Autoscan Can't Scan): {stats['failed']}\n-----")

    # Print game-specific autoscan text
    if CMain.gamevars["game"] == "Fallout4":
        print(yamldata.autoscan_text)

    # Print error message if no logs were scanned
    if stats["scanned"] == 0 and stats["incomplete"] == 0:
        print("\n❌ CLASSIC found no crash logs to scan or the scan failed.")
        print("    There are no statistics to show (at this time).\n")

    # Print information about failed scans
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


def process_version_info(segments: CrashLogSegments, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Process version information from the crash log."""
    version_current = crashgen_version_gen(segments.crashgen_version)
    version_latest = crashgen_version_gen(yamldata.crashgen_latest_og)
    version_latest_vr = crashgen_version_gen(yamldata.crashgen_latest_vr)

    autoscan_report.extend((
        f"\nMain Error: {segments.mainerror}\n",
        f"Detected {yamldata.crashgen_name} Version: {segments.crashgen_version} \n",
    ))

    if version_current >= version_latest or version_current >= version_latest_vr:
        autoscan_report.append(f"* You have the latest version of {yamldata.crashgen_name}! *\n\n")
    else:
        autoscan_report.append(f"{yamldata.warn_outdated} \n")


def get_gpu_info(system_segment: list[str]) -> tuple[bool, bool, bool]:
    """Extract GPU information from system segment."""
    gpu_amd = any("GPU #1" in elem and "AMD" in elem for elem in system_segment)
    gpu_nvidia = any("GPU #1" in elem and "Nvidia" in elem for elem in system_segment)
    gpu_integrated = not gpu_amd and not gpu_nvidia

    return gpu_amd, gpu_nvidia, gpu_integrated


def get_crash_log_plugins(segments: CrashLogSegments, ignore_plugins_list: set[str]) -> PluginDict:
    """Extract and process plugins from crash log."""
    crashlog_plugins: PluginDict = {}

    # Check if main game ESM exists in plugins
    esm_name = f"{CMain.gamevars['game']}.esm"
    if not any(esm_name in elem for elem in segments.plugins):
        return crashlog_plugins

    # Check for loadorder.txt
    loadorder_path = Path("loadorder.txt")
    if loadorder_path.exists():
        with loadorder_path.open(encoding="utf-8", errors="ignore") as f:
            loadorder_data = f.readlines()
        for elem in loadorder_data[1:]:
            if all(elem not in item for item in crashlog_plugins):
                crashlog_plugins[elem] = "LO"
        return crashlog_plugins

    # Process plugins from crash log
    pluginsearch = re.compile(r"\s*\[(FE:([0-9A-F]{3})|[0-9A-F]{2})\]\s*(.+?(?:\.es[pml])+)", flags=re.IGNORECASE)
    for elem in segments.plugins:
        pluginmatch = pluginsearch.match(elem)
        if pluginmatch is None:
            continue

        plugin_fid = pluginmatch.group(1)
        plugin_name = pluginmatch.group(3)

        if plugin_fid is not None and all(plugin_name not in item for item in crashlog_plugins):
            crashlog_plugins[plugin_name] = plugin_fid.replace(":", "")
        elif plugin_name and "dll" in plugin_name.lower():
            crashlog_plugins[plugin_name] = "DLL"
        else:
            crashlog_plugins[plugin_name] = "???"

    # Add XSE modules
    for elem in segments.xsemodules_lower:
        if all(elem not in item for item in crashlog_plugins):
            crashlog_plugins[elem] = "DLL"

    # Add Vulkan modules
    for elem in segments.allmodules:
        if "vulkan" in elem.lower():
            elem_parts = elem.strip().split(" ", 1)
            elem_parts[1] = "DLL"
            if all(elem_parts[0] not in item for item in crashlog_plugins):
                crashlog_plugins[elem_parts[0]] = elem_parts[1]

    # Remove ignored plugins
    for signal in ignore_plugins_list:
        if signal in crashlog_plugins:
            del crashlog_plugins[signal]

    return crashlog_plugins


def process_crash_suspects(segments: CrashLogSegments, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Process and report crash suspects."""
    autoscan_report.extend((
        "====================================================\n",
        "CHECKING IF LOG MATCHES ANY KNOWN CRASH SUSPECTS...\n",
        "====================================================\n",
    ))

    crashlog_mainerror_lower = segments.mainerror.lower()
    if ".dll" in crashlog_mainerror_lower and "tbbmalloc" not in crashlog_mainerror_lower:
        autoscan_report.extend((
            "* NOTICE : MAIN ERROR REPORTS THAT A DLL FILE WAS INVOLVED IN THIS CRASH! * \n",
            "If that dll file belongs to a mod, that mod is a prime suspect for the crash. \n-----\n",
        ))

    trigger_suspect_found = False
    max_warn_length = 30

    # Check error list
    for error, signal in yamldata.suspects_error_list.items():
        error_severity, error_name = error.split(" | ", 1)
        if signal in segments.mainerror:
            error_name = error_name.ljust(max_warn_length, ".")
            autoscan_report.append(f"# Checking for {error_name} SUSPECT FOUND! > Severity : {error_severity} # \n-----\n")
            trigger_suspect_found = True

    # Check stack list
    for error in yamldata.suspects_stack_list:
        error_severity, error_name = error.split(" | ", 1)
        error_req_found = error_opt_found = stack_found = False
        signal_list = yamldata.suspects_stack_list.get(error, [])
        has_required_item = False

        for signal in signal_list:
            if "|" not in signal:
                if signal in segments.callstack_intact:
                    stack_found = True
                continue

            signal_modifier, signal_string = signal.split("|", 1)
            match signal_modifier:
                case "ME-REQ":
                    has_required_item = True
                    if signal_string in segments.mainerror:
                        error_req_found = True
                case "ME-OPT":
                    if signal_string in segments.mainerror:
                        error_opt_found = True
                case "NOT" if signal_string in segments.callstack_intact:
                    break
                case _ if signal_modifier.isdecimal():
                    if segments.callstack_intact.count(signal_string) >= int(signal_modifier):
                        stack_found = True

        if (has_required_item and error_req_found) or (not has_required_item and (error_opt_found or stack_found)):
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


def process_plugins(
    segments: CrashLogSegments, crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]
) -> None:
    """Process and report plugin information."""
    autoscan_report.append("# LIST OF (POSSIBLE) PLUGIN SUSPECTS #\n")

    segment_callstack_lower = [line.lower() for line in segments.callstack]
    plugins_matches = [
        plugin
        for line in segment_callstack_lower
        for plugin in (p.lower() for p in crashlog_plugins)
        if plugin in line
        and "modified by:" not in line
        and all(ignore not in plugin for ignore in (x.lower() for x in yamldata.game_ignore_plugins))
    ]

    if plugins_matches:
        plugins_found = dict(Counter(plugins_matches))
        autoscan_report.extend(f"- {key} | {value}\n" for key, value in plugins_found.items())
        autoscan_report.extend((
            "\n[Last number counts how many times each Plugin Suspect shows up in the crash log.]\n",
            f"These Plugins were caught by {yamldata.crashgen_name} and some of them might be responsible for this crash.\n",
            "You can try disabling these plugins and check if the game still crashes, though this method can be unreliable.\n\n",
        ))
    else:
        autoscan_report.append("* COULDN'T FIND ANY PLUGIN SUSPECTS *\n\n")


def process_mod_conflicts(crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Check and report mod conflicts."""
    autoscan_report.extend((
        "====================================================\n",
        "CHECKING FOR MODS THAT CONFLICT WITH OTHER MODS...\n",
        "====================================================\n",
    ))

    if crashlog_plugins:
        if detect_mods_double(yamldata.game_mods_conf, crashlog_plugins, autoscan_report):
            autoscan_report.extend((
                "# [!] CAUTION : FOUND MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n",
                "* YOU SHOULD CHOOSE WHICH MOD TO KEEP AND DISABLE OR COMPLETELY REMOVE THE OTHER MOD * \n\n",
            ))
        else:
            autoscan_report.append("# FOUND NO MODS THAT ARE INCOMPATIBLE OR CONFLICT WITH YOUR OTHER MODS # \n\n")
    else:
        autoscan_report.append(yamldata.warn_noplugins)


def process_mod_solutions(crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Check and report available mod solutions."""
    autoscan_report.extend((
        "====================================================\n",
        "CHECKING FOR MODS WITH SOLUTIONS & COMMUNITY PATCHES\n",
        "====================================================\n",
    ))

    if crashlog_plugins:
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


def process_mod_patches(crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Check and report OPC patched mods."""
    if CMain.gamevars["game"] != "Fallout4":
        return

    autoscan_report.extend((
        "====================================================\n",
        "CHECKING FOR MODS PATCHED THROUGH OPC INSTALLER...\n",
        "====================================================\n",
    ))

    if crashlog_plugins:
        if detect_mods_single(yamldata.game_mods_opc2, crashlog_plugins, autoscan_report):
            autoscan_report.extend((
                "\n* FOR PATCH REPOSITORY THAT PREVENTS CRASHES AND FIXES PROBLEMS IN THESE AND OTHER MODS,* \n",
                "* VISIT OPTIMIZATION PATCHES COLLECTION: https://www.nexusmods.com/fallout4/mods/54872 * \n\n",
            ))
        else:
            autoscan_report.append("# FOUND NO PROBLEMATIC MODS THAT ARE ALREADY PATCHED THROUGH THE OPC INSTALLER # \n\n")
    else:
        autoscan_report.append(yamldata.warn_noplugins)


def process_important_mods(
    crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, gpu_rival: Literal["nvidia", "amd"] | None, autoscan_report: list[str]
) -> None:
    """Check and report important mod presence and compatibility."""
    autoscan_report.extend((
        "====================================================\n",
        "CHECKING IF IMPORTANT PATCHES & FIXES ARE INSTALLED\n",
        "====================================================\n",
    ))

    if crashlog_plugins:
        if any("londonworldspace" in plugin.lower() for plugin in crashlog_plugins):
            detect_mods_important(yamldata.game_mods_core_folon, crashlog_plugins, autoscan_report, gpu_rival)
        else:
            detect_mods_important(yamldata.game_mods_core, crashlog_plugins, autoscan_report, gpu_rival)
    else:
        autoscan_report.append(yamldata.warn_noplugins)


def process_records(segments: CrashLogSegments, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]) -> None:
    """Process and report record information."""
    autoscan_report.append("# LIST OF DETECTED (NAMED) RECORDS #\n")

    lower_records = [record.lower() for record in yamldata.classic_records_list]
    lower_ignore = [record.lower() for record in yamldata.game_ignore_records]

    records_matches = [
        line[30:].strip() if "[RSP+" in line else line.strip()
        for line in segments.callstack
        if any(item in line.lower() for item in lower_records) and all(record not in line.lower() for record in lower_ignore)
    ]

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


def process_mod_compatibility(
    crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, gpu_info: tuple[bool, bool, bool], autoscan_report: list[str]
) -> None:
    """Process and report mod compatibility information."""
    gpu_amd, gpu_nvidia, _ = gpu_info
    gpu_rival = "nvidia" if (gpu_amd) else "amd" if gpu_nvidia else None

    autoscan_report.extend((
        "====================================================\n",
        "CHECKING FOR MODS THAT CAN CAUSE FREQUENT CRASHES...\n",
        "====================================================\n",
    ))

    if crashlog_plugins:
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

    process_mod_conflicts(crashlog_plugins, yamldata, autoscan_report)
    process_mod_solutions(crashlog_plugins, yamldata, autoscan_report)
    process_mod_patches(crashlog_plugins, yamldata, autoscan_report)
    from typing import cast

    process_important_mods(
        crashlog_plugins,
        yamldata,
        cast(Literal["nvidia", "amd"] | None, gpu_rival if gpu_rival in ["nvidia", "amd"] else None),
        autoscan_report,
    )


def process_formids(
    segments: CrashLogSegments, crashlog_plugins: PluginDict, show_formid_values: bool, formid_db_exists: bool, autoscan_report: list[str]
) -> None:
    """Process and report FormID information from the crash log."""
    autoscan_report.append("# LIST OF (POSSIBLE) FORM ID SUSPECTS #\n")

    # Extract FormIDs from callstack
    formids_matches = [line.replace("0x", "").strip() for line in segments.callstack if "0xFF" not in line and "id:" in line.lower()]

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
            f"These Form IDs were caught by {segments.crashgen_version} and some of them might be related to this crash.\n",
            "You can try searching any listed Form IDs in xEdit and see if they lead to relevant records.\n\n",
        ))
    else:
        autoscan_report.append("* COULDN'T FIND ANY FORM ID SUSPECTS *\n\n")


def get_fcx_check_results() -> tuple[str, str]:
    """Get FCX mode check results."""
    fcx_mode = CMain.classic_settings(bool, "FCX Mode")
    if fcx_mode:
        main_files_check = CMain.main_combined_result()
        game_files_check = CGame.game_combined_result()
    else:
        main_files_check = "❌ FCX Mode is disabled, skipping game files check... \n-----\n"
        game_files_check = ""
    return main_files_check, game_files_check


def process_crash_details(
    segments: CrashLogSegments, crashlog_plugins: PluginDict, yamldata: ClassicScanLogsInfo, autoscan_report: list[str]
) -> None:
    """Process and report detailed crash information."""
    show_formid_values = CMain.classic_settings(bool, "Show FormID Values") or False
    formid_db_exists = any(db.is_file() for db in DB_PATHS)

    # Process plugins
    process_plugins(segments, crashlog_plugins, yamldata, autoscan_report)

    # Process FormIDs
    process_formids(segments, crashlog_plugins, show_formid_values, formid_db_exists, autoscan_report)

    # Process records
    process_records(segments, yamldata, autoscan_report)


def process_crash_log(
    crash_file: Path, yamldata: ClassicScanLogsInfo, ignore_plugins_list: set[str], main_files_check: str, game_files_check: str
) -> tuple[list[str], bool, bool]:
    """Process a single crash log file and return the report, success flags."""
    autoscan_report: list[str] = []
    trigger_scan_failed = False
    trigger_plugins_loaded = False

    # Initialize report header
    autoscan_report.extend([
        f"{crash_file.name} -> AUTOSCAN REPORT GENERATED BY {yamldata.classic_version} \n",
        "# FOR BEST VIEWING EXPERIENCE OPEN THIS FILE IN NOTEPAD++ OR SIMILAR # \n",
        "# PLEASE READ EVERYTHING CAREFULLY AND BEWARE OF FALSE POSITIVES # \n",
        "====================================================\n",
    ])

    # Read and parse crash log
    crash_data = read_crash_log(crash_file)
    if len(crash_data) < 20:
        return autoscan_report, True, False

    # Parse log segments
    segments = parse_crash_log_segments(crash_data, yamldata.xse_acronym, yamldata.crashgen_name)

    # Process crash log version info
    process_version_info(segments, yamldata, autoscan_report)

    # Get crash log plugins
    crashlog_plugins = get_crash_log_plugins(segments, ignore_plugins_list)
    trigger_plugins_loaded = bool(crashlog_plugins)

    # Process GPU info
    gpu_info = get_gpu_info(segments.system)

    # Process crash suspects
    process_crash_suspects(segments, yamldata, autoscan_report)

    # Add FCX mode info and results
    fcx_mode = CMain.classic_settings(bool, "FCX Mode")
    if fcx_mode:
        autoscan_report.extend([
            "* NOTICE: FCX MODE IS ENABLED. CLASSIC MUST BE RUN BY THE ORIGINAL USER FOR CORRECT DETECTION * \n",
            "[ To disable mod & game files detection, disable FCX Mode in the exe or CLASSIC Settings.yaml ] \n\n",
        ])
    else:
        autoscan_report.extend([
            "* NOTICE: FCX MODE IS DISABLED. YOU CAN ENABLE IT TO DETECT PROBLEMS IN YOUR MOD & GAME FILES * \n",
            "[ FCX Mode can be enabled in the exe or CLASSIC Settings.yaml located in your CLASSIC folder. ] \n\n",
        ])

    # Process specific mod setups (Xcell, BakaScrapHeap, etc)
    process_special_mods(segments.xsemodules_lower, yamldata, crashlog_plugins, autoscan_report)

    # Add FCX check results
    autoscan_report.append(main_files_check)
    if game_files_check:
        autoscan_report.append(game_files_check)

    # Process mod compatibility
    process_mod_compatibility(crashlog_plugins, yamldata, gpu_info, autoscan_report)

    # Process crash details
    process_crash_details(segments, crashlog_plugins, yamldata, autoscan_report)

    return autoscan_report, trigger_scan_failed, trigger_plugins_loaded


def process_special_mods(xsemodules: set[str], yamldata: ClassicScanLogsInfo, crashgen: dict[str, Any], autoscan_report: list[str]) -> None:
    """Process special mods like XCell and BakaScrapHeap."""
    Has_XCell = "x-cell-fo4.dll" in xsemodules
    Has_BakaScrapHeap = "bakascrapheap.dll" in xsemodules

    if not CMain.classic_settings(bool, "FCX Mode"):
        if Has_XCell:
            yamldata.crashgen_ignore.update(("MemoryManager", "HavokMemorySystem", "ScaleformAllocator", "SmallBlockAllocator"))
        elif Has_BakaScrapHeap:
            yamldata.crashgen_ignore.add("MemoryManager")

        # Process crashgen settings
        if crashgen:
            for setting_name, setting_value in crashgen.items():
                if setting_value is False and setting_name not in yamldata.crashgen_ignore:
                    autoscan_report.append(
                        f"* NOTICE : {setting_name} is disabled in your {yamldata.crashgen_name} settings, is this intentional? * \n-----\n"
                    )

            # Process specific crashgen settings
            process_crashgen_settings(crashgen, yamldata, xsemodules, autoscan_report)


def crashlogs_scan() -> None:
    """Main function to scan crash logs."""
    # Setup
    crashlog_list = crashlogs_get_files()

    print("REFORMATTING CRASH LOGS, PLEASE WAIT...\n")
    remove_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_records") or []
    crashlogs_reformat(crashlog_list, remove_list)

    print("SCANNING CRASH LOGS, PLEASE WAIT...\n")
    scan_start_time = time.perf_counter()

    # Initialize yaml data and settings
    yamldata = ClassicScanLogsInfo()
    ignore_plugins_list = {item.lower() for item in yamldata.ignore_list} if yamldata.ignore_list else set()

    # Get FCX check results once
    main_files_check, game_files_check = get_fcx_check_results()

    # Initialize statistics
    stats = {"scanned": 0, "incomplete": 0, "failed": 0}

    scan_failed_list: list[str] = []

    # Process each crash log
    crashlogs = SQLiteReader(crashlog_list)
    for crashlog_file in crashlog_list:
        autoscan_report, trigger_scan_failed, trigger_plugins_loaded = process_crash_log(
            crashlog_file, yamldata, ignore_plugins_list, main_files_check, game_files_check
        )

        # Update statistics
        stats["scanned"] += 1
        if trigger_scan_failed:
            stats["scanned"] -= 1
            stats["failed"] += 1
            scan_failed_list.append(crashlog_file.name)
        if not trigger_plugins_loaded:
            stats["incomplete"] += 1

        # Write report
        write_autoscan_report(crashlog_file, autoscan_report)

        # Move unsolved logs if needed
        if trigger_scan_failed and CMain.classic_settings(bool, "Move Unsolved Logs"):
            move_unsolved_logs(crashlog_file)

    # Cleanup and final output
    crashlogs.close()
    print_final_stats(stats, scan_start_time, scan_failed_list, yamldata)


if __name__ == "__main__":
    CMain.initialize()
    from pathlib import Path

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

    if (
        isinstance(args.ini_path, Path)
        and args.ini_path.resolve().is_dir()
        and str(args.ini_path) != CMain.classic_settings(str, "INI Folder Path")
    ):
        CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.INI Folder Path", str(args.ini_path.resolve()))

    if (
        isinstance(args.scan_path, Path)
        and args.scan_path.resolve().is_dir()
        and str(args.scan_path) != CMain.classic_settings(str, "SCAN Custom Path")
    ):
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
