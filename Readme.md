===========================================================================

# LINKS #

AUTO-SCANNER NEXUS PAGE : https://www.nexusmods.com/fallout4/mods/56255

BUFFOUT 4 NEXUS PAGE : https://www.nexusmods.com/fallout4/mods/47359

HOW TO INSTALL BUFFOUT 4 : https://www.nexusmods.com/fallout4/articles/3115

HOW TO READ CRASH LOGS : https://docs.google.com/document/d/17FzeIMJ256xE85XdjoPvv_Zi3C5uHeSTQh6wOZugs4c

FOR WINDOWS 7 SUPPORT, INSTALL THIS PYTHON VERSION: https://github.com/NulAsh/cpython/releases OR USE

AUTO-SCANNER GUI VERSION by MakeHate (Yagami Light): https://www.nexusmods.com/fallout4/mods/63346
(GUI Version 1.2 right now is severely out of date and reports some false positives, so beware.)

===========================================================================
# CONTENTS #

Crash Log Auto-Scanner is bundled with several files:

*Scan Readme.md* - The file that you're reading right now.

*Scan Crashlogs.py* - Main script for scanning crash logs generated by Buffout 4. You can place this file into your Documents\My Games\Fallout4\F4SE folder
and run Scan Crashlogs.py by double clicking on it. After scanning completes, close the cmd window, then open any -AUTOSCAN.md file and read what they say.

*Scan Crashlogs.ini* - Configuration file for *Scan Crashlogs.py* where some parameters can be adjusted.

*HOW TO USE AUTO SCANNER.gif* - Looping gif that shows how the script should be used. Don't forget to install Python!

*HOW TO READ CRASH LOGS.pdf* - Document that lists most common Buffout 4 crash log messages and errors, and ways to prevent or fix them.

*CL TOOLS* - Folder with extra scripts for advanced crash log file searching and troubleshooting. (Useful if you like to hoard crash logs).

===========================================================================
# HOW TO READ AUTOSCAN FILES #

After running *Scan Crashlogs.py*, you'll see the following in any *crash-time-and-date-AUTOSCAN.md* output file:
==========
The part above the Main Error shows the name of the scanned crash log and the Auto-Scanner version that was used.

The Main Error segment shows the main error message type and call stack address where the crash likely originates from.
In 95% of cases, the main error will be "EXCEPTION_ACCESS_VIOLATION", meaning the game couldn't access some required data for one reason or another.
The next part is the program or file where the crash originates from and lastly the call stack address that was last accessed before the crash occurred.
NOTE: The call stack address and its values have NOTHING to do with any Plugin or Game IDs. Don't bother trying to match these numbers with your load order.

The part below the Main Error shows the version of Buffout 4 that was used when the crash log was generated and the latest version of Buffout 4 available.

* CHECKING IF BUFFOUT4.TOML PARAMETERS ARE CORRECT * segment checks the Buffout4.toml file inside the game's Fallout 4\Data\F4SE\Plugins folder.
Depending on which mods you have installed, you might need to manually correct the parameters in Buffout4.toml with a text editor as explained by this segment.

* CHECKING IF LOG MATCHES ANY KNOWN CRASH MESSAGES * segment checks the database of all crash errors that are either known about or can be solved.
If any crash messages show CULPRIT FOUND!, this requires that you OPEN the "How To Read Crash Logs" PDF included with the auto-scanner archive
or the online version of that same document and look up all detected crash messages / errors.

* CHECKING FOR MODS THAT CAN CAUSE FREQUENT CRASHES * segment checks the database for mods that are known to cause major problems or frequently crash the game.
You are supposed to temporarily disable any mods detected here and recheck your game to see if the crash went away. If not, continue to the next segments. 

* CHECKING FOR MODS WITH SOLUTIONS & COMMUNITY PATCHES * segment checks the database for mods that can cause various problems or crashes,
but already have available fixes or alternatives as explained by this segment. You should visit this Important Patches & Fixes article:
https://www.nexusmods.com/fallout4/articles/3769 which lists all important community patches and fixes for the base game and various mods.

* CHECKING FOR MODS PATCHED THROUGH OPC INSTALLER * segment checks the database for mods that are patched through my own Optimization Patches Collection mod.
You are supposed to visit this page https://www.nexusmods.com/fallout4/mods/54872, then download and install the main file with your mod manager.

* SCANNING THE LOG FOR SPECIFIC (POSSIBLE) CUPLRITS * segment checks the crash log for any
mentions of Plugins, FormIDs or Game Files that were possibly involved when this crash occurred.
If you weren't able to fix the crash so far, you can search for any Game Files, look up any FormIDs in FO4Edit
or disable any Plugins listed in this segment to further confirm if they caused this crash or not. If all else fails, perform a Binary Search.

===========================================================================
# THINGS TO DO IF NO CRASH LOGS ARE GIVEN OR IF AUTO-SCAN DOESN'T HELP #

0. Make sure that you've installed all Buffout 4 requirements correctly! And it's best that you install everything manually, WITHOUT using your Mod Manager!
Install all programs manually and files by manually placing them into required folders. This ensures that all required files are ALWAYS loaded by the game.

1. Run Plugin Checker in Wrye Bash and do what it says. Instructions at the end of this article: https://www.nexusmods.com/fallout4/articles/3115

2. Run FO4Edit and load all of your mods, then select all mod plugins (CTRL + A), right click and check for errors.
If any plugins have a bunch of errors (IGNORE Base Game and DLC plugins), disable or clean them by using Quick Auto Clean from FO4Edit
or by opening and resaving that plugin with the Creation Kit. Manually install Creation Kit Fixes as well: https://www.nexusmods.com/fallout4/mods/51165

3. Carefully read both https://www.nexusmods.com/fallout4/articles/3115 for list of mods that frequently cause crashes or other problems and
https://www.nexusmods.com/fallout4/articles/3769 for list of important community patches and fixes for the base game and mods.
Disable, fix, test and install any mods relevant to your situation. If all else fails, perform a binary search.

4. Reset your INI files. This is done by deleting all .ini files inside your Documents\My Games\Fallout4 folder and running the game
once directly through Fallout4Launcher.exe. Once you reach the main menu, exit the game and run BethINI to readjust INI settings.

5. Find the culprit(s) through a BINARY SEARCH. Sometimes, your only viable option is brute force. Instructions below.

===========================================================================
# BINARY SEARCH 101 #

It's an algorithm (method) for tracking down the exact crash culprit as fast as possible when crash logs aren't helpful. Here's a clear example on how to do it.
Of course, this method can (very) rarely backfire since the game could crash due to missing scripts from deactivated content, but it is what it is.
Let's say you have 200 activated plugins in total, and let's give all those plugins arbitrary names. (Plugin1, Plugin2, Plugin3... all the way to Plugin200).

First, backup your latest save before doing this! Saves are located in your Documents\My Games\Fallout4\Saves folder.
Your goal is to disable half, only leave all plugins from Plugin1 to Plugin100 enabled. After that:

-> If the game crashes again, then you know the culprit is somewhere between Plugin1 and Plugin100.  Now you disable half of those, so you only leave plugins from
Plugin1 to Plugin50 enabled and test again. Each time you crash, disable half of the plugin range from which you deduced it must contain the crashing mod.

-> If the game doesn't crash,  then you know the culprit is somewhere between Plugin101 and Plugin200. Now enable half of the ones you disabled, so you leave plugins from
Plugin101 to Plugin150 enabled and test again. Each time you don't crash, enable half of the plugin range from which you deduced it must contain the crashing mod.

Repeat this logic until you're (hopefully) left with one mod that you had to leave disabled for the game not to crash, and that's your culprit.
Basically, for each group of mods you disable, whichever half crashes is the one that contains the Impostor. Use your sussy brain to vote him out. ඞ
After that, enable all other mods and continue from the save before you stared the binary search (in case you kept making exit saves while testing it out). 
Another example, with mods A, B, C, D, E, F, G and H:

ABCDEFGH
Crash

ABCD | EFGH
Crash

AB | CD EFGH
Crash

A | B CDEFGH
No Crash

B must be the sussy boi since the game didn't crash with only Mod A enabled while all other mods are disabled, but it did crash with both Mod A & B enabled.

===========================================================================
# CHANGELOG #

(Future updates will likely take much longer due to lack of feedback / data for some crash errors.)
(Porting Auto-Scanner to Skyrim will be next. If you're reading this and want to help, let me know.)

5.15
* MAIN SCRIPT *
- Auto-Scanner is now available on GitHub! https://github.com/GuidanceOfGrace/Buffout4-CLAS
- Added missing Water Collision Crash stat logging while *Stat Logging = true* in *Scan Crashlogs.ini*
- Auto-Scanner now checks if *loadorder.txt* is located in the same folder where you run the script from.
  [If it's found, Auto-Scanner will ignore plugins from all crash logs and scan only the plugins from loadorder.txt]
  [Useful if you want to prevent Auto-Scanner from detecting certain plugins, as you can easily edit loadorder.txt]

* OTHER FILES *
- Additional adjustments to CL Full Scan.py and CL Compare.py to prevent scripts from crashing.
- Small changes and fixes for the Readme documentation.

5.05 (Hotfix)
* MAIN SCRIPT *
- Changed code logic for detecting locations of required log and ini files to prevent crashes.

* OTHER FILES *
- Added Unicode encoding to CL Full Scan.py and CL Compare.py so they are much less likely to crash.

5.00 
* MAIN SCRIPT *
- Auto updates for pip package installation will now stay disabled by default until I find actual packages to install.
- Main cmd terminal will show basic stats. For additional stats, set Stat Logging to *true* in *Scan Crashlogs.ini*.
- Auto-Scanner now sets FCX Mode to *true* by default upon generating its ini file. (Open ini for more details.)
- Auto-Scanner no longer checks if Fallout4.ini exists, since the file is no longer checked for anything else.
- Auto-Scanner no longer prompts to manually input the game path, a better alternative method was found.
- Auto-Scanner will prompt to manually input the Fallout4.ini path if known default paths aren't found.
- Various text formatting changes to make important messages more noticeable in -AUTOSCAN.md outputs.
- Added detection for Water Collision Crash. If you get this crash error/message, contact me asap.
- Adjusted code logic for Console Command Crash to reduce the amount of false positives.
- Fixed errors with "'Address_Library' / 'FO4_Custom_Path' is not defined".

+ If FCX Mode is *true*, Auto-Scanner checks for errors in log files inside your Documents\My Games\Fallout4\F4SE folder.
+ If FCX Mode is *true*, Auto-Scanner checks for errors and correct Buffout 4 \ F4SE installation in the f4se.log file.
  [f4se.log is located in Documents\My Games\Fallout4\F4SE folder and auto-generates after each game run.]

* OTHER FILES *
- Updated "How To Read Crash Logs" PDF so it matches the latest online version (Table of Contents should be done soon).
- Removed text about Scan Crashlogs FCX.py from *Scan Readme.md*, since that's now a setting in *Scan Crashlogs.ini*

- *Scan Crashlogs.ini* (generates after running the main script) has a new setting called *Move Unsolved = false*
  [Set to true if you want Auto-Scanner to move all unsolved logs and their autoscans to CLAS-UNSOLVED folder.]
  [Unsolved logs are all crash logs where Auto-Scanner didn't detect any known crash errors or messages.]

- *Scan Crashlogs.ini* (generates after running the main script) has a new setting called *INI Path = *
  [Only required if Profile Specific INIs are enabled in MO2 or you moved your Documents folder somewhere else.]
  [I highly recommend that you disable Profile Specific Game INI Files in MO2, located in Tools > Profiles...]
  
4.20 (The Funny Number Update)
- Auto-Scanner now auto-generates a custom ini file to save some of its confguration settings.
  [Check the file after running the script once to see and modify available settings.]

- Fixed unsolved [Precombines Crash] counting the wrong error messages when detected.
- Removed Autoscan logging for Buffout4.toml settings from the script, as this was unnecessary.
- Added script details and instructions on how to read AUTOSCAN.md outputs to Scan Readme.md file.
- Adjusted POSSIBLE FORM ID CULRIPTS code logic to not look for dynamic IDs (those that start with FF).

+ If FCX Mode is *true*, Auto-Scanner will automatically try to correct settings in Buffout4.toml if needed.
+ If FCX Mode is *true*, Auto-Scanner will check if Buffout 4 files/requirements are correctly installed.

4.10
- Hotfix: Auto-Scanner now checks multiple drives to find required folders & INI files.
- Fixed prompt for having to manually enter the game path if game folder wasn't detected.
- [This should also fix false positives given by Auto-Scanner versions 4.00 and 4.04.]

4.04
- Hotfix: Changed how Fallout4Custom.ini is created/accessed so it hopefully doesn't fail.
- Forgot to include the PDF in version 4.00. You can always use the online version:
- [Updated "How To Read Crash Logs" PDF so it matches the online version.]

4.00
> Major Change: Auto-Scanner now checks if all Buffout 4 files are correctly installed/configured.
  It also checks if Archive Invalidation / Loose Files setting is enabled and automatically
  adds required text to Fallout4Custom.ini to force-enable that setting if necessary.
  (Auto-Scanner may ask that you input your Fallout 4 game path if it's not found.)

- Auto-Scanner will now automatically update pip installer for future use of Python Modules.
- Added detection for F4SE, Buffout 4, Address Library (& Plugin Preloader) installation.
- Fixed code logic for "Rendering Crash" to increase detection accuracy.
- Added detection for 3 new mods with community patches and solutions.

3.50
- General code improvements and optimization for my own sanity.
- Fixed code logic for Plugin Limit Crash to reduce false positives.
- Added detection for around 5 new mods with community patches and solutions.
- Updated "How To Read Crash Logs" PDF so it matches the latest online version.
- Added short descriptions about issues and possible solutions for most detected mods.
- Auto-Scanner now checks for all known game file extensions when looking for FILE CULPRITS.
- Auto-Scanner should no longer make duplicate plugin / mod reports, let me know if it still does.
- Expanded "NPC Pathing Crash" to also cover dynamic pathing / pathfinding error messages.
- Improved code logic for few other crash messages / errors to increase detection accuracy.
- Added detection for the following crash types (unconfirmed only, check PDF for details):
> *[Item Crash]
> *[Input Crash]
> *[Bad INI Crash]
> *[NPC Patrol Crash]
> *[NPC Projectile Crash]

3.20
- Updated advised fix instructions for HUD Caps mod.
- Improved detection logic for some mods to reduce duplicate reports.
- Added detection for around 10 new mods with community patches and solutions.
- Added detection for 4 new unsolved crash messages and errors (see PDF).
- Added detection for the MO2 Extractor Crash

3.11
- Fixed code logic for Audio Driver Crash to reduce false positives.
- Fixed code logic and added detection for .DDS and .SWF files in POSSIBLE FILE CULPRITS
- Improved code logic for some crash messages / errors to increase detection accuracy.
- Added detection for the following crash types:
> LOD Crash
> Decal Crash
> Vulkan Memory Crash
> Vulkan Settings Crash
> Corrupted Audio Crash

3.00
> Major Change: Auto-Scanner archive now contains a PDF file named "How To Read Crash Logs"
(It's a dictionary of all known crash messages / errors and their solutions, alternatives and fixes.)
(I've removed the same info from crash log article because Nexus formatting is absolutely awful.)

- Removed check for TBB Redistributables as they are no longer required for Buffout 1.25.0+
- Fixed Windows 7 support. You should still install Python with Win7 support from the link.
- Fixed detection priority for CHW and mods that are guaranteed to crash with it.
- Moved Unofficial Patch detection to "MODS WITH SOLUTIONS AND ALTERNATIVES"
- Added detection for the official High Resolution Textures DLC (HD DLC). It's crap, don't use it.
- Added detection for possible file culprits, mainly .NIF and .BGSM , but other types might show up.
- Added detection for 4 new mods that frequently cause crashes listed in the main crash log article.
- Added detection for around 7 new crash messages / errors now listed in the included PDF document. 
- Changed names of some crash messages / errors so they better signify the underlying problem.
- Changed AUTOSCAN output format from .txt to .md for better readability and formatting.
- Added statistics logging at the end of Scan Crashlogs main console window.
- Various minor improvements and optimizations to Auto-Scanner code.

2.00
> Major Improvement: Auto-Scanner will now scan all available crash logs in one run.
(This also completely removes the need to copy-paste crash log names each time.)

- Added Priority Levels to each crash culprit. Handy when there are multiple culprits.
(Higher Priority Level means the crash was more likely caused by that exact culprit.)

- Auto-Scanner now also checks if any Autoscan results came out empty due to errors.
- Changed AUTOSCAN output format from .log to .txt (also helps with sorting).
- Main Error is now listed at the top of each AUTOSCAN result for clarity sake.
- Additional improvements to plugin detection to further reduce duplicate reports.
- Added additional check for new Papyrus | VirtualMachine (Papyrus Crash).
- Fixed incorrectly capitalized hyperlinks so they actually work.
- Corrected plugin detection for the Subway Runner mod.
- Renamed "Object Nif Crash" to "Object Model Crash".
- Updated example gif with the new instructions.

1.22
- Small improvements to plugin detection in order to reduce duplicate reports.
- Added additional check for yet undefined 0x0 Crash (Zero Crash). If you get it, please upload it to one of listed sites.
- Improved Classic Holstered Weapons detection logic so it gives a warning if you have mods that are guaranteed to crash with CHW.

1.20
- Upgrade: Auto-Scanner now lists Plugin IDs next to detected plugins whenever possible, as suggested by user: 1ae0bfb8
(Makes it much easier to tell if first two (or three if esl flagged) Form ID numbers match any Plugin ID numbers.)

- Improved "LIST OF (POSSIBLE) PLUGIN CULRIPTS" logic so it doesn't list empty spaces or base game plugins.
- Corrected nvwgf2umx.dll (Nvidia Driver Crash) detection logic so it's less likely to give false positives.

- Renamed "Weapon Physics Crash" to "Weapon Animation Crash" so it's less likely to be mistaken for Weapon Debris Crash
- Renamed "Havok Physics Crash" to "Body Physics Crash" so it better reflects the actual problem when such is detected.
- Added various other improvements and details to the script. Updated Scan Example.gif and added Scan Changelog.txt.

Version 1.13
- Hotfix: Small adjustment to Achievements settings detection logic so it doesn't leave false positives.

Version 1.11
- Beta release. May contain false positives. Please report if it does.
