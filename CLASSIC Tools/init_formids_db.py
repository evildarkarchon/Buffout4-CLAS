import os
import sqlite3
from pathlib import Path
from typing import Literal
base_path = Path("../CLASSIC Data/databases")

path_fallout4_formids_db = base_path / "Fallout4 FormIDs.db"
path_fallout4_formids_db.unlink(missing_ok=True)

path_skyrim_formids_db = base_path / "Skyrim FormIDs.db"
path_skyrim_formids_db.unlink(missing_ok=True)

path_starfield_formids_db = base_path / "Starfield FormIDs.db"
path_starfield_formids_db.unlink(missing_ok=True)

path_fallout4_fid_main = base_path / "Fallout4 FID Main.txt"
if path_fallout4_fid_main.exists():
    with sqlite3.connect(path_fallout4_formids_db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS Fallout4
              (id INTEGER PRIMARY KEY AUTOINCREMENT,
               plugin TEXT, formid TEXT, entry TEXT)''')
        conn.execute("CREATE INDEX IF NOT EXISTS Fallout4_index ON Fallout4(formid, plugin COLLATE nocase);")
        if conn.in_transaction:
            conn.commit()

path_skyrim_fid_main = base_path / "Skyrim FID Main.txt"
if path_skyrim_fid_main.exists():
    with sqlite3.connect(path_skyrim_formids_db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS Skyrim
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 plugin TEXT, formid TEXT, entry TEXT)''')
        conn.execute("CREATE INDEX IF NOT EXISTS Skyrim_index ON Skyrim (formid, plugin COLLATE nocase);")
        if conn.in_transaction:
            conn.commit()

path_starfield_fid_main = base_path / "Starfield FID Main.txt"
if path_starfield_fid_main.exists():
    with sqlite3.connect(path_starfield_formids_db) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS Starfield
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 plugin TEXT, formid TEXT, entry TEXT)''')
        conn.execute("CREATE INDEX IF NOT EXISTS Starfield_index ON Starfield (formid, plugin COLLATE nocase);")
    if conn.in_transaction:
        conn.commit()

def insert(lines: list[str], table: Literal["Fallout4", "Skyrim", "Starfield"] = "Fallout4") -> None:
    with sqlite3.connect(f"../CLASSIC Data/databases/{table} FormIDs.db") as conn:
        c = conn.cursor()
        if lines:
            for line in lines:
                line = line.strip()
                if "|" in line and len(line.split(" | ")) >= 3:
                    plugin, formid, entry, *extra = line.split(" | ")  # the *extra is for any extraneous data that might be in the line (Python thinks there are more than 3 items in the list for some reason)
                    c.execute(f'''INSERT INTO {table} (plugin, formid, entry)
                          VALUES (?, ?, ?)''', (plugin, formid, entry))
            if conn.in_transaction:
                conn.commit()

path_fallout4_fid_mods = base_path / "Fallout4 FID Mods.txt"
if path_fallout4_fid_main.exists():
    print("Inserting Fallout 4 Main FormIDs...")
    with path_fallout4_fid_main.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines())
if path_fallout4_fid_mods.exists():
    print("Inserting Fallout 4 Mod FormIDs...")
    with path_fallout4_fid_mods.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines())

path_skyrim_fid_mods = base_path / "Skyrim FID Mods.txt"
if path_skyrim_fid_main.exists():
    print("Inserting Skyrim Main FormIDs...")
    with path_skyrim_fid_main.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines(), "Skyrim")

if path_skyrim_fid_mods.exists():
    print("Inserting Skyrim Mod FormIDs...")
    with path_skyrim_fid_mods.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines(), "Skyrim")

path_starfield_fid_mods = base_path / "Starfield FID Mods.txt"
if path_starfield_fid_main.exists():
    print("Inserting Starfield Main FormIDs...")
    with path_starfield_fid_main.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines(), "Starfield")

if path_starfield_fid_mods.exists():
    print("Inserting Starfield Mod FormIDs...")
    with path_starfield_fid_mods.open(encoding="utf-8", errors="ignore") as f:
        insert(f.readlines(), "Starfield")
