import sqlite3
from pathlib import Path

base_path = Path("../CLASSIC Data/databases")


def insert(lines: list[str], game: str, path_db: Path) -> None:
    with sqlite3.connect(path_db) as conn:
        c = conn.cursor()
        for line in lines:
            line = line.strip()
            parts = line.split(" | ", maxsplit=3)
            if len(parts) >= 3:
                # the _ catches any extraneous data that might be in the line
                plugin, formid, entry, _ = parts
                c.execute(
                    f"""INSERT INTO {game} (plugin, formid, entry) VALUES (?, ?, ?)""",
                    (plugin, formid, entry),
                )
        if conn.in_transaction:
            conn.commit()


for game in ("Fallout4", "Skyrim", "Starfield"):
    path_db = base_path / f"{game} FormIDs.db"
    path_main = base_path / f"{game} FID Main.txt"
    path_mods = base_path / f"{game} FID Mods.txt"
    path_db.unlink(missing_ok=True)

    if path_main.exists():
        with sqlite3.connect(path_db) as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {game}
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                plugin TEXT, formid TEXT, entry TEXT)"""
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS {game}_index ON {game} (formid, plugin COLLATE nocase);")
            if conn.in_transaction:
                conn.commit()

        print(f"Inserting {game} Main FormIDs...")
        with path_main.open(encoding="utf-8", errors="ignore") as f:
            insert(f.readlines(), game, path_db)

    if path_mods.exists():
        print(f"Inserting {game} Mod FormIDs...")
        with path_mods.open(encoding="utf-8", errors="ignore") as f:
            insert(f.readlines(), game, path_db)
