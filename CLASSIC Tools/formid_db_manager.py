import sqlite3
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class FormIDManager(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("FormID Database Manager")

        # Create main widget and its main layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        self.main_layout = QVBoxLayout(main_widget)

        # Create UI elements
        self.create_file_selection()
        self.create_database_selection()
        self.create_game_selection()
        self.create_mode_selection()
        self.create_log_area()
        self.create_process_button()

        # Set window properties
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

    def create_file_selection(self) -> None:
        layout = QHBoxLayout()

        self.file_label = QLabel("FormID List File:")
        self.file_path = QLineEdit()
        self.file_path.setPlaceholderText("No file selected")
        select_file_btn = QPushButton("Select File")
        select_file_btn.clicked.connect(self.select_file)

        layout.addWidget(self.file_label)
        layout.addWidget(self.file_path, 1)
        layout.addWidget(select_file_btn)

        self.main_layout.addLayout(layout)

    def create_database_selection(self) -> None:
        layout = QHBoxLayout()

        self.db_label = QLabel("Database File:")
        self.db_path = QLineEdit()
        self.db_path.setPlaceholderText("No database selected")
        select_db_btn = QPushButton("Select Database")
        select_db_btn.clicked.connect(self.select_database)

        layout.addWidget(self.db_label)
        layout.addWidget(self.db_path, 1)
        layout.addWidget(select_db_btn)

        self.main_layout.addLayout(layout)

    def create_game_selection(self) -> None:
        layout = QHBoxLayout()

        self.game_label = QLabel("Game:")
        self.game_combo = QComboBox()
        self.game_combo.addItems(["Fallout4", "Skyrim", "Starfield"])

        layout.addWidget(self.game_label)
        layout.addWidget(self.game_combo)
        layout.addStretch()

        self.main_layout.addLayout(layout)

    def create_mode_selection(self) -> None:
        layout = QHBoxLayout()

        self.mode_checkbox = QCheckBox("Update Mode (replaces existing entries)")
        self.verbose_checkbox = QCheckBox("Verbose Output")
        self.dry_run_checkbox = QCheckBox("Dry Run (preview changes)")
        self.dry_run_checkbox.stateChanged.connect(self.switch_verbose_checkbox_enabled)

        layout.addWidget(self.mode_checkbox)
        layout.addWidget(self.verbose_checkbox)
        layout.addWidget(self.dry_run_checkbox)
        layout.addStretch()

        self.main_layout.addLayout(layout)

    def create_log_area(self) -> None:
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.main_layout.addWidget(self.log_area)

    def create_process_button(self) -> None:
        self.process_btn = QPushButton("Process FormIDs")
        self.process_btn.clicked.connect(self.process_formids)
        self.main_layout.addWidget(self.process_btn)

    def select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select FormID List", "", "Text Files (*.txt)")
        if file_path:
            self.file_path.setText(str(file_path))

    def select_database(self) -> None:
        db_path, _ = QFileDialog.getOpenFileName(self, "Select Database", "", "Database Files (*.db)")
        if db_path:
            self.db_path.setText(str(db_path))

    def log(self, message: str) -> None:
        self.log_area.append(message)
        QApplication.processEvents()  # Ensures UI updates during processing

    def switch_verbose_checkbox_enabled(self) -> None:
        self.verbose_checkbox.setEnabled(not self.dry_run_checkbox.isChecked())
        if self.dry_run_checkbox.isChecked():  # Doing it this way because I don't want to automatically check it when disabling dry run.
            self.verbose_checkbox.setChecked(False)

    def process_formids(self) -> None:
        # Get all necessary values
        game = self.game_combo.currentText()
        file_path = Path(self.file_path.text())
        db_path = Path(self.db_path.text()) if self.db_path.text() != "No database selected" else Path.cwd() / f"{game}.db"
        update_mode = self.mode_checkbox.isChecked()
        verbose = self.verbose_checkbox.isChecked()
        dry_run = self.dry_run_checkbox.isChecked()

        if dry_run:
            self.log("DRY RUN MODE - No changes will be made to the database")

        # Validate inputs
        if not file_path.exists() or self.file_path.text() == "No file selected":
            self.log("Error: FormID list file not found")
            return

        if not db_path.parent.exists():
            self.log("Error: Database file not found, creating in current directory.")
            db_path.touch()

        try:
            # For dry run, we'll check the database structure without creating anything
            with sqlite3.connect(db_path if db_path.exists() else ":memory:") as conn:
                cursor = conn.cursor()

                # Check if table exists
                cursor.execute(f"""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='{game}'
                """)
                table_exists = cursor.fetchone() is not None

                # Check if index exists
                cursor.execute(f"""
                    SELECT name FROM sqlite_master
                    WHERE type='index' AND name='{game}_index'
                """)
                index_exists = cursor.fetchone() is not None

                # Report what would be created
                if not table_exists:
                    msg = "Would create" if dry_run else "Creating"
                    self.log(f"{msg} table {game}...")
                    if not dry_run:
                        conn.execute(
                            f"""CREATE TABLE IF NOT EXISTS {game}
                            (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            plugin TEXT, formid TEXT, entry TEXT)"""
                        )

                if not index_exists:
                    msg = "Would create" if dry_run else "Creating"
                    self.log(f"{msg} index {game}_index...")
                    if not dry_run:
                        conn.execute(
                            f"CREATE INDEX IF NOT EXISTS {game}_index ON {game} (formid, plugin COLLATE nocase);"
                        )

                if not dry_run and conn.in_transaction:
                    conn.commit()

            # Process the FormID list to show what would happen
            plugins_to_process = set()
            entry_count = 0

            with file_path.open(encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if " | " not in line:
                        continue

                    parts = line.split(" | ", maxsplit=2)
                    if len(parts) != 3:
                        continue

                    plugin, formid, entry = parts
                    plugins_to_process.add(plugin)
                    entry_count += 1

            # Report summary of what would happen
            if dry_run:
                self.log("\nDry run summary:")
                self.log(f"Found {entry_count} valid entries to process")
                self.log(f"Found {len(plugins_to_process)} unique plugins:")
                for plugin in sorted(plugins_to_process):
                    if update_mode:
                        self.log(f"- Would delete existing entries for {plugin}")
                    self.log(f"- Would add entries from {plugin}")
                self.log("\nNo changes were made to the database (dry run mode)")
                return

            # If not dry run, proceed with actual processing
            with sqlite3.connect(db_path) as conn, file_path.open(encoding="utf-8", errors="ignore") as f:
                c = conn.cursor()
                self.log(f"Processing FormIDs from {file_path} for {game}")

                plugins_deleted = []
                plugins_announced = []

                for line in f:
                    line = line.strip()
                    if " | " not in line:
                        continue

                    parts = line.split(" | ", maxsplit=2)
                    if len(parts) != 3:
                        continue

                    plugin, formid, entry = parts

                    if update_mode:
                        if plugin not in plugins_deleted:
                            self.log(f"Deleting {plugin}'s FormIDs from {game}")
                            c.execute(f"DELETE FROM {game} WHERE plugin = ?", (plugin,))
                            plugins_deleted.append(plugin)
                        if plugin not in plugins_announced and not verbose:
                            self.log(f"Adding {plugin}'s FormIDs to {game}")
                            plugins_announced.append(plugin)

                    if verbose:
                        self.log(f"Adding {line} to {game}")

                    c.execute(
                        f"INSERT INTO {game} (plugin, formid, entry) VALUES (?, ?, ?)",
                        (plugin, formid, entry),
                    )

                if conn.in_transaction:
                    conn.commit()

                self.log("Optimizing database...")
                c.execute("vacuum")

                self.log("Processing completed successfully!")

        except (OSError, sqlite3.DatabaseError) as e:
            self.log(f"Error during processing: {e!s}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FormIDManager()
    window.show()
    sys.exit(app.exec())
