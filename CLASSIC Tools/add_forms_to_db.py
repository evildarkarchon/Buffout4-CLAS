import sqlite3
from pathlib import Path
from typing import Literal

from tap import Tap


class Arguments(Tap):
    """Adds a FormID list to the specified game and database."""

    file: Path = Path("FormID_List.txt")
    """Path to the FormID list file"""

    table: Literal["Fallout4", "Skyrim", "Starfield"] = "Fallout4"
    """Game for which the database is being updated"""

    db: Path = Path("../CLASSIC Data/databases/Fallout4 FormIDs Local.db")
    """Path to the database file"""

    verbose: bool = False
    """Enable verbose output"""


args = Arguments().parse_args()

if not args.file.exists():
    msg = f"File {args.file} not found"
    raise FileNotFoundError(msg)

if not args.db.exists():
    msg = f"Database {args.db} not found, creating it..."
    with sqlite3.connect(args.db) as conn:
        conn.execute(
            f"""CREATE TABLE IF NOT EXISTS {args.table}
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
            plugin TEXT, formid TEXT, entry TEXT)"""
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS {args.table}_index ON {args.table} (formid, plugin COLLATE nocase);")
        if conn.in_transaction:
            conn.commit()

with sqlite3.connect(args.db) as conn, args.file.open(encoding="utf-8", errors="ignore") as f:
    c = conn.cursor()
    if args.verbose:
        print(f"Adding FormIDs from {args.file} to {args.table}")
    for line in f:
        line = line.strip()
        parts = line.split(" | ", maxsplit=3)
        if len(parts) >= 3:
            if args.verbose:
                print(f"Adding {line} to {args.table}")
            # the _ catches any extraneous data that might be in the line
            plugin, formid, entry, _ = parts
            c.execute(
                f"INSERT INTO {args.table} (plugin, formid, entry) VALUES (?, ?, ?)",
                (plugin, formid, entry),
            )
    if conn.in_transaction:
        conn.commit()
    if args.verbose:
        print("Optimizing database...")
    c.execute("vacuum")
