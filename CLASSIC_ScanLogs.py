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
@dataclass
class CrashLogSegments:
    """Container for crash log segments."""
    crashgen: list[str] = field(default_factory=list)
    system: list[str] = field(default_factory=list)
    callstack: list[str] = field(default_factory=list)
    allmodules: list[str] = field(default_factory=list)
    xsemodules: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)

    @property
    def callstack_intact(self) -> str:
        """Get callstack as a single string."""
        return "".join(self.callstack)


class CrashLogAnalyzer:
    def __init__(self, crash_data: list[str], yamldata: ClassicScanLogsInfo):
        self.crash_data = crash_data
        self.yamldata = yamldata
        self.segments: CrashLogSegments | None = None
        self.crashlog_plugins: dict[str, str] = {}
        self.crashlog_plugins_lower: set[str] = set()
        self.xsemodules: set[str] = set()  # Store XSE module names
        self.gpu_rival: Literal["nvidia", "amd"] | None = None
        self.trigger_plugins_loaded = False
        self.trigger_plugin_limit = False
        self.trigger_limit_check_disabled = False
        self.trigger_scan_failed = False
        self.game_version: Version | None = None
        self.crashgen_version: str = ""
        self.main_error: str = ""

        # Initialize plugin search regex
        self.pluginsearch = re.compile(
            r"\s*\[(FE:([0-9A-F]{3})|[0-9A-F]{2})\]\s*(.+?(?:\.es[pml])+)",
            flags=re.IGNORECASE
        )

    def analyze_crash_log(self) -> list[str]:
        """Main analysis method that orchestrates the crash log analysis."""
        autoscan_report: list[str] = []

        # Parse segments and store info
        self.game_version = crashgen_version_gen(self._parse_segments())

        # Process plugins
        self._process_plugins()

        # Check game version against plugin limit
        if "[FF]" in "".join(self.segments.plugins if self.segments else []):
            if self.game_version in (self.yamldata.game_version, self.yamldata.game_version_vr):
                self.trigger_plugin_limit = True
            elif self.game_version >= self.yamldata.game_version_new:
                self.trigger_limit_check_disabled = True

        # Generate report sections
        self._generate_header(autoscan_report)
        self._check_suspects(autoscan_report)
        self._check_settings(autoscan_report)
        self._check_frequent_crashes(autoscan_report)
        self._check_mod_conflicts(autoscan_report)
        self._check_solutions(autoscan_report)
        self._check_opc_patches(autoscan_report)
        self._check_important_mods(autoscan_report)
        self._analyze_suspects(autoscan_report)

        return autoscan_report

    def _parse_segments(self) -> str:
        """Parse crash log into segments and store info."""
        gameversion, self.crashgen_version, self.main_error, segments = find_segments(
            self.crash_data,
            self.yamldata.xse_acronym,
            self.yamldata.crashgen_name
        )

        self.segments = CrashLogSegments(*segments)

        # Process GPU info
        self._detect_gpu_type()

        return gameversion

    def _detect_gpu_type(self) -> None:
        """Detect GPU type from system info."""
        if not self.segments:
            return

        crashlog_GPUAMD = any("GPU #1" in elem and "AMD" in elem
                              for elem in self.segments.system)
        crashlog_GPUNV = any("GPU #1" in elem and "Nvidia" in elem
                             for elem in self.segments.system)

        if crashlog_GPUAMD or not crashlog_GPUNV:
            self.gpu_rival = "nvidia"
        elif crashlog_GPUNV:
            self.gpu_rival = "amd"

    def _process_plugins(self) -> None:
        """Process and store plugin information."""
        if not self.segments:
            return

        # Process main plugins
        for elem in self.segments.plugins:
            pluginmatch = self.pluginsearch.match(elem)
            if not pluginmatch:
                continue

            plugin_fid = pluginmatch.group(1)
            plugin_name = pluginmatch.group(3)

            if plugin_fid and plugin_name not in self.crashlog_plugins:
                self.crashlog_plugins[plugin_name] = plugin_fid.replace(":", "")
            elif plugin_name and "dll" in plugin_name.lower():
                self.crashlog_plugins[plugin_name] = "DLL"
            else:
                self.crashlog_plugins[plugin_name] = "???"

        # Process additional modules
        self._process_additional_modules()

        # Create lowercase version for case-insensitive lookups
        self.crashlog_plugins_lower = {
            plugin.lower() for plugin in self.crashlog_plugins
        }

    def _process_additional_modules(self) -> None:
        """Process additional modules from xsemodules and allmodules."""
        if not self.segments:
            return

        def _process_xse_module_name(module: str) -> str:
            """Extract and normalize module name, stripping version if present."""
            _DLL_VERSION_PATTERN = "dll v"
            return module.split(" v", 1)[0].strip() if _DLL_VERSION_PATTERN in module else module.strip()

        # Refactored processing into a helper function _process_xse_module_name
        # noinspection PyTypeChecker
        self.xsemodules = {
            _process_xse_module_name(x) for x in {y.lower() for y in self.segments.xsemodules}
        }

        # Add XSE modules to plugins
        for elem in self.xsemodules:
            if elem not in self.crashlog_plugins:
                self.crashlog_plugins[elem] = "DLL"

        # Process Vulkan modules
        for elem in self.segments.allmodules:
            if "vulkan" in elem.lower():
                elem_parts = elem.strip().split(" ", 1)
                if elem_parts[0] not in self.crashlog_plugins:
                    self.crashlog_plugins[elem_parts[0]] = "DLL"

    def _check_suspects(self, report: list[str]) -> None:
        """Check for known crash suspects."""
        if not self.segments:
            return

        # Check main error
        if ".dll" in self.segments.callstack_intact.lower():
            report.append(
                "* NOTICE: Main error indicates DLL involvement in crash *\n"
                "This suggests the responsible mod may be identified by the DLL.\n"
            )

        # Check against known patterns
        for error, signals in self.yamldata.suspects_stack_list.items():
            if self._check_suspect_pattern(signals):
                severity, name = error.split(" | ", 1)
                report.append(
                    f"# Found {name} suspect pattern! Severity: {severity} #\n"
                )

    def _check_suspect_pattern(self, signals: list[str]) -> bool:
        """Check if crash matches a suspect pattern."""
        if not self.segments:
            return False

        found_required = False
        found_optional = False

        for signal in signals:
            if "|" not in signal:
                if signal in self.segments.callstack_intact:
                    return True
                continue

            mod, pattern = signal.split("|", 1)

            if mod == "ME-REQ":
                found_required = pattern in self.segments.callstack_intact
            elif mod == "ME-OPT":
                found_optional = pattern in self.segments.callstack_intact
            elif mod.isdigit():
                count = self.segments.callstack_intact.count(pattern)
                if count >= int(mod):
                    return True

        return found_required or found_optional

    def _generate_header(self, report: list[str]) -> None:
        """Generate the header section of the report."""
        if not self.segments:
            return

        # Add file header
        report.extend([
            f"{self.yamldata.classic_version} -> AUTOSCAN REPORT\n",
            "# FOR BEST VIEWING EXPERIENCE OPEN THIS FILE IN NOTEPAD++ OR SIMILAR #\n",
            "# PLEASE READ EVERYTHING CAREFULLY AND BEWARE OF FALSE POSITIVES #\n",
            "====================================================\n\n"
        ])

        # Add version info
        version_current = crashgen_version_gen(self.segments.crashgen[0] if self.segments.crashgen else "")
        version_latest = crashgen_version_gen(self.yamldata.crashgen_latest_og)
        version_latest_vr = crashgen_version_gen(self.yamldata.crashgen_latest_vr)

        report.extend([
            f"Detected {self.yamldata.crashgen_name} Version: {version_current}\n",
            "* You have the latest version! *\n" if (version_current >= version_latest or
                                                     version_current >= version_latest_vr) else f"{self.yamldata.warn_outdated}\n"
        ])

    def _check_settings(self, report: list[str]) -> None:
        """Check various settings and generate report section."""
        if not self.segments:
            return

        report.extend([
            "====================================================\n",
            "CHECKING IF NECESSARY FILES/SETTINGS ARE CORRECT...\n",
            "====================================================\n"
        ])

        # Check FCX mode
        fcx_mode = CMain.classic_settings(bool, "FCX Mode")
        if fcx_mode:
            report.extend([
                "* NOTICE: FCX MODE IS ENABLED. CLASSIC MUST BE RUN BY THE ORIGINAL USER FOR CORRECT DETECTION *\n",
                "[ To disable mod & game files detection, disable FCX Mode in the exe or CLASSIC Settings.yaml ]\n\n"
            ])
        else:
            report.extend([
                "* NOTICE: FCX MODE IS DISABLED. YOU CAN ENABLE IT TO DETECT PROBLEMS IN YOUR MOD & GAME FILES *\n",
                "[ FCX Mode can be enabled in the exe or CLASSIC Settings.yaml located in your CLASSIC folder. ]\n\n"
            ])

        # Get module info
        Has_XCell = "x-cell-fo4.dll" in self.xsemodules
        Has_BakaScrapHeap = "bakascrapheap.dll" in self.xsemodules

        # Process crashgen settings
        if not fcx_mode:
            if Has_XCell:
                self.yamldata.crashgen_ignore.update(
                    ("MemoryManager", "HavokMemorySystem", "ScaleformAllocator", "SmallBlockAllocator"))
            elif Has_BakaScrapHeap:
                self.yamldata.crashgen_ignore.add("MemoryManager")

            # Parse crashgen settings section
            crashgen_settings: dict[str, bool | int | str] = {}
            if self.segments.crashgen:
                for elem in self.segments.crashgen:
                    if ":" in elem:
                        key, value = elem.split(":", 1)
                        crashgen_settings[key] = True if value == " true" else False if value == " false" else int(
                            value) if value.strip().isdecimal() else value.strip()

                # Check disabled settings
                for setting_name, setting_value in crashgen_settings.items():
                    if setting_value is False and setting_name not in self.yamldata.crashgen_ignore:
                        report.append(
                            f"* NOTICE : {setting_name} is disabled in your {self.yamldata.crashgen_name} settings, is this intentional? *\n-----\n"
                        )

                # Check Achievements setting
                if (achievements := crashgen_settings.get("Achievements")) is not None:
                    if achievements and (
                            "achievements.dll" in self.crashlog_plugins_lower or "unlimitedsurvivalmode.dll" in self.crashlog_plugins_lower):
                        report.extend([
                            "# ❌ CAUTION : The Achievements Mod and/or Unlimited Survival Mode is installed, but Achievements is set to TRUE #\n",
                            f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change Achievements to FALSE, this prevents conflicts with {self.yamldata.crashgen_name}.\n-----\n"
                        ])
                    else:
                        report.append(
                            f"✔️ Achievements parameter is correctly configured in your {self.yamldata.crashgen_name} settings!\n-----\n"
                        )

                # Check Memory Manager settings
                if (memory_manager := crashgen_settings.get("MemoryManager")) is not None:
                    if memory_manager:
                        if Has_XCell:
                            report.extend([
                                "# ❌ CAUTION : X-Cell is installed, but MemoryManager parameter is set to TRUE #\n",
                                f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change MemoryManager to FALSE, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                            if Has_BakaScrapHeap:
                                report.extend([
                                    "# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with X-Cell #\n",
                                    " FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with X-Cell.\n-----\n"
                                ])
                        elif Has_BakaScrapHeap:
                            report.extend([
                                f"# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with {self.yamldata.crashgen_name} #\n",
                                f" FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with {self.yamldata.crashgen_name}.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ Memory Manager parameter is correctly configured in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )
                    elif Has_XCell:
                        if Has_BakaScrapHeap:
                            report.extend([
                                "# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with X-Cell #\n",
                                " FIX: Uninstall the Baka ScrapHeap Mod, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ Memory Manager parameter is correctly configured for use with X-Cell in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )
                    elif Has_BakaScrapHeap:
                        report.extend([
                            f"# ❌ CAUTION : The Baka ScrapHeap Mod is installed, but is redundant with {self.yamldata.crashgen_name} #\n",
                            f" FIX: Uninstall the Baka ScrapHeap Mod and open {self.yamldata.crashgen_name}'s TOML file and change MemoryManager to TRUE, this improves performance.\n-----\n"
                        ])

                # Check X-Cell specific settings
                if Has_XCell:
                    # Check HavokMemorySystem
                    if (havok := crashgen_settings.get("HavokMemorySystem")) is not None:
                        if havok:
                            report.extend([
                                "# ❌ CAUTION : X-Cell is installed, but HavokMemorySystem parameter is set to TRUE #\n",
                                f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change HavokMemorySystem to FALSE, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ HavokMemorySystem parameter is correctly configured for use with X-Cell in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )

                    # Check BSTextureStreamerLocalHeap
                    if (bs_texture := crashgen_settings.get("BSTextureStreamerLocalHeap")) is not None:
                        if bs_texture:
                            report.extend([
                                "# ❌ CAUTION : X-Cell is installed, but BSTextureStreamerLocalHeap parameter is set to TRUE #\n",
                                f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change BSTextureStreamerLocalHeap to FALSE, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ BSTextureStreamerLocalHeap parameter is correctly configured for use with X-Cell in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )

                    # Check ScaleformAllocator
                    if (scaleform := crashgen_settings.get("ScaleformAllocator")) is not None:
                        if scaleform:
                            report.extend([
                                "# ❌ CAUTION : X-Cell is installed, but ScaleformAllocator parameter is set to TRUE #\n",
                                f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change ScaleformAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ ScaleformAllocator parameter is correctly configured for use with X-Cell in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )

                    # Check SmallBlockAllocator
                    if (small_block := crashgen_settings.get("SmallBlockAllocator")) is not None:
                        if small_block:
                            report.extend([
                                "# ❌ CAUTION : X-Cell is installed, but SmallBlockAllocator parameter is set to TRUE #\n",
                                f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change SmallBlockAllocator to FALSE, this prevents conflicts with X-Cell.\n-----\n"
                            ])
                        else:
                            report.append(
                                f"✔️ SmallBlockAllocator parameter is correctly configured for use with X-Cell in your {self.yamldata.crashgen_name} settings!\n-----\n"
                            )

                # Check F4EE (LooksMenu) setting
                if (f4ee := crashgen_settings.get("F4EE")) is not None:
                    if not f4ee and "f4ee.dll" in self.crashlog_plugins_lower:
                        report.extend([
                            "# ❌ CAUTION : Looks Menu is installed, but F4EE parameter under [Compatibility] is set to FALSE #\n",
                            f" FIX: Open {self.yamldata.crashgen_name}'s TOML file and change F4EE to TRUE, this prevents bugs and crashes from Looks Menu.\n-----\n"
                        ])
                    else:
                        report.append(
                            f"✔️ F4EE (Looks Menu) parameter is correctly configured in your {self.yamldata.crashgen_name} settings!\n-----\n"
                        )

    def _check_frequent_crashes(self, report: list[str]) -> None:
        """Check for mods known to cause frequent crashes."""
        if not self.trigger_plugins_loaded:
            report.append(self.yamldata.warn_noplugins)
            return

        report.append("\n=== CHECKING FOR FREQUENT CRASH CAUSES ===\n")

        if detect_mods_single(self.yamldata.game_mods_freq, self.crashlog_plugins, report):
            report.extend([
                "# WARNING: Above mods are known to cause frequent crashes #\n",
                "Consider disabling them temporarily to confirm crash cause\n"
            ])
        else:
            report.append("No known problematic mods detected\n")

    def _check_mod_conflicts(self, report: list[str]) -> None:
        """Check for known mod conflicts."""
        if not self.trigger_plugins_loaded:
            report.append(self.yamldata.warn_noplugins)
            return

        report.append("\n=== CHECKING FOR MOD CONFLICTS ===\n")

        if detect_mods_double(self.yamldata.game_mods_conf, self.crashlog_plugins, report):
            report.extend([
                "# WARNING: Found incompatible mod combinations #\n",
                "Please review and resolve the conflicts above\n"
            ])
        else:
            report.append("No known mod conflicts detected\n")

    def _check_solutions(self, report: list[str]) -> None:
        """Check for mods with known solutions or patches."""
        if not self.trigger_plugins_loaded:
            report.append(self.yamldata.warn_noplugins)
            return

        report.append("\n=== CHECKING FOR AVAILABLE SOLUTIONS ===\n")

        if detect_mods_single(self.yamldata.game_mods_solu, self.crashlog_plugins, report):
            report.extend([
                "# Solutions available for problematic mods detected above #\n",
                "Review the suggestions and apply appropriate fixes\n"
            ])
        else:
            report.append("No mods with known solutions detected\n")

    def _check_opc_patches(self, report: list[str]) -> None:
        """Check for mods that can be patched with OPC."""
        if CMain.gamevars["game"] != "Fallout4" or not self.trigger_plugins_loaded:
            return

        report.append("\n=== CHECKING FOR OPC PATCH AVAILABILITY ===\n")

        if detect_mods_single(self.yamldata.game_mods_opc2, self.crashlog_plugins, report):
            report.extend([
                "# Mods above can be patched with OPC #\n",
                "Visit: https://www.nexusmods.com/fallout4/mods/54872\n"
            ])
        else:
            report.append("No mods requiring OPC patches detected\n")

    def _check_important_mods(self, report: list[str]) -> None:
        """Check for important mods and patches."""
        if not self.trigger_plugins_loaded:
            report.append(self.yamldata.warn_noplugins)
            return

        report.append("\n=== CHECKING FOR IMPORTANT MODS ===\n")

        # Check London-specific mods if relevant
        if any("londonworldspace" in plugin.lower() for plugin in self.crashlog_plugins):
            detect_mods_important(self.yamldata.game_mods_core_folon,
                                  self.crashlog_plugins, report, self.gpu_rival)
        else:
            detect_mods_important(self.yamldata.game_mods_core,
                                  self.crashlog_plugins, report, self.gpu_rival)

    def _analyze_suspects(self, report: list[str]) -> None:
        """Analyze and report on crash suspects."""
        if not self.segments:
            return

        report.append("\n=== ANALYZING CRASH SUSPECTS ===\n")

        # Check plugin suspects
        self._analyze_plugin_suspects(report)

        # Check FormID suspects
        self._analyze_formid_suspects(report)

        # Check record suspects
        self._analyze_record_suspects(report)

    def _analyze_plugin_suspects(self, report: list[str]) -> None:
        """Analyze and report plugin suspects."""
        # noinspection PyTypeChecker
        plugins_matches = [
            plugin for line in map(str.lower, self.segments.callstack)
            for plugin in self.crashlog_plugins_lower
            if plugin in line and "modified by:" not in line
        ]

        if plugins_matches:
            report.append("# PLUGIN SUSPECTS #\n")
            counter = Counter(plugins_matches)
            for plugin, count in counter.items():
                report.append(f"- {plugin} | {count}\n")
        else:
            report.append("No plugin suspects identified\n")

    def _analyze_formid_suspects(self, report: list[str]) -> None:
        """Analyze and report FormID suspects."""
        formids_matches = [
            line.replace("0x", "").strip()
            for line in self.segments.callstack
            if "0xFF" not in line and "id:" in line.lower()
        ]

        if formids_matches:
            report.append("# FORMID SUSPECTS #\n")
            for formid in formids_matches:
                report.append(f"- {formid}\n")
        else:
            report.append("No FormID suspects identified\n")

    def _analyze_record_suspects(self, report: list[str]) -> None:
        """Analyze and report record suspects."""
        lower_records = [record.lower() for record in self.yamldata.classic_records_list]
        lower_ignore = [record.lower() for record in self.yamldata.game_ignore_records]

        records_matches = [
            line.strip() for line in self.segments.callstack
            if any(item in line.lower() for item in lower_records)
               and not any(record in line.lower() for record in lower_ignore)
        ]

        if records_matches:
            report.append("# RECORD SUSPECTS #\n")
            counter = Counter(records_matches)
            for record, count in counter.items():
                report.append(f"- {record} | {count}\n")
        else:
            report.append("No record suspects identified\n")


class CrashLogProcessor:
    """Main class for processing crash logs."""

    def __init__(self, yamldata: ClassicScanLogsInfo):
        self.yamldata = yamldata
        self.stats_scanned = 0
        self.stats_incomplete = 0
        self.stats_failed = 0
        self.scan_failed_list: list[str] = []

    def process_logs(self) -> None:
        """Process all crash logs."""
        crash_files = crashlogs_get_files()

        print("Reformatting crash logs...")
        remove_list = CMain.yaml_settings(list[str], CMain.YAML.Main, "exclude_log_records") or []
        crashlogs_reformat(crash_files, remove_list)

        print("Scanning crash logs...")
        scan_start_time = time.perf_counter()

        # Process each log
        sqlite_reader = SQLiteReader(crash_files)
        for crash_file in crash_files:
            self._process_single_log(crash_file, sqlite_reader)

        sqlite_reader.close()

        # Generate final report
        self._generate_final_report(scan_start_time)

    def _process_single_log(self, crash_file: Path, sqlite_reader: SQLiteReader) -> None:
        """Process a single crash log file."""
        crash_data = sqlite_reader.read_log(crash_file.name)

        analyzer = CrashLogAnalyzer(crash_data, self.yamldata)
        autoscan_report = analyzer.analyze_crash_log()

        # Update statistics
        self._update_stats(analyzer)

        # Write report
        self._write_report(crash_file, autoscan_report)

        # Handle failed scans
        if analyzer.trigger_scan_failed:
            self.scan_failed_list.append(crash_file.name)

    def _update_stats(self, analyzer: CrashLogAnalyzer) -> None:
        """Update scan statistics."""
        self.stats_scanned += 1
        if not analyzer.segments or not analyzer.segments.plugins:
            self.stats_incomplete += 1
        if analyzer.trigger_scan_failed:
            self.stats_failed += 1
            self.stats_scanned -= 1

    @staticmethod
    def _write_report(crash_file: Path, report: list[str]) -> None:
        """Write analysis report to file."""
        report_path = crash_file.with_name(crash_file.stem + "-AUTOSCAN.md")
        report_path.write_text(
            "".join(report),
            encoding="utf-8",
            errors="ignore"
        )

    def _generate_final_report(self, start_time: float) -> None:
        """Generate and print final report."""
        print("\nScan complete!")
        print(f"Random hint: {random.choice(self.yamldata.classic_game_hints)}")
        print(f"\nScanned in {time.perf_counter() - start_time:.2f} seconds")
        print(f"Successfully scanned: {self.stats_scanned}")
        print(f"Incomplete logs: {self.stats_incomplete}")
        print(f"Failed scans: {self.stats_failed}")


def crashlogs_scan() -> None:
    """Main entry point for crash log scanning."""
    yamldata = ClassicScanLogsInfo()
    processor = CrashLogProcessor(yamldata)
    processor.process_logs()


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
