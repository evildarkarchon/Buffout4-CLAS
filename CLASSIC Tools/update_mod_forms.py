import sqlite3
from pathlib import Path
from typing import Literal

from tap import Tap


class Args(Tap):
    """Updates the database with entries from a FormID list for the specified game and database.
    This will delete all FormIDs from existing plugins referenced in the file and replace them with the new ones."""

    file: Path = Path("FormID_List.txt")
    table: Literal["Fallout4", "Skyrim", "Starfield"] = "Fallout4"
    db: Path = Path("../CLASSIC Data/databases/Fallout4 FormIDs Local.db")
    verbose: bool = False

args = Args().parse_args()

if not Path(args.db).is_file():
    raise FileNotFoundError(f"Database {args.db} not found")



with sqlite3.connect(args.db) as conn, args.file.open(encoding="utf-8", errors="ignore") as f:
    c = conn.cursor()
    if not args.verbose:
        print(f"Updating database with FormIDs from {args.file} to {args.table}")
    plugins_deleted = []
    plugins_announced = []
    for line in f:
        line = line.strip()
        if " | " in line:
            data = line.split(" | ")
            if len(data) >= 3:
                plugin, formid, entry, *extra = data
                if plugin not in plugins_deleted:
                    print(f"Deleting {plugin}'s FormIDs from {args.table}")
                    c.execute(f"delete from {args.table} where plugin = ?", (plugin,))
                    plugins_deleted.append(plugin)
                if plugin not in plugins_announced and not args.verbose:
                    print(f"Adding {plugin}'s FormIDs to {args.table}")
                    plugins_announced.append(plugin)
                if args.verbose:
                    print(f"Adding {line} to {args.table}")
                c.execute(f"""INSERT INTO {args.table} (plugin, formid, entry)
                    VALUES (?, ?, ?)""", (plugin, formid, entry))
    if conn.in_transaction:
        conn.commit()
    print("Optimizing database...")
    c.execute("vacuum")
