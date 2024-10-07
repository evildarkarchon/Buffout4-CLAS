import sqlite3
from pathlib import Path
from typing import Literal

from tap import Tap


class Arguments(Tap):
    """Adds a FormID list to the specified game and database."""

    file: Path = Path("FormID_List.txt")  # The file to add to the database
    table: Literal["Fallout4", "Skyrim", "Starfield"] = "Fallout4"  # The table to add the file to
    db: Path = Path("../CLASSIC Data/databases/Fallout4 FormIDs.db")  # "The database to add the file to"
    verbose: bool = False  # Prints out the lines as they are added


args = Arguments().parse_args()

if not args.file.exists():
    msg = f"File {args.file} not found"
    raise FileNotFoundError(msg)

if not args.db.exists():
    msg = f"Database {args.db} not found"
    raise FileNotFoundError(msg)

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
