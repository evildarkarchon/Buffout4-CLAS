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
        self.file_path = QLabel("No file selected")
        select_file_btn = QPushButton("Select File")
        select_file_btn.clicked.connect(self.select_file)

        layout.addWidget(self.file_label)
        layout.addWidget(self.file_path, 1)
        layout.addWidget(select_file_btn)

        self.main_layout.addLayout(layout)

    def create_database_selection(self) -> None:
        layout = QHBoxLayout()

        self.db_label = QLabel("Database File:")
        self.db_path = QLabel("No database selected")
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

        layout.addWidget(self.mode_checkbox)
        layout.addWidget(self.verbose_checkbox)
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

    def process_formids(self) -> None:
        # Get all necessary values
        file_path = Path(self.file_path.text())
        db_path = Path(self.db_path.text())
        game = self.game_combo.currentText()
        update_mode = self.mode_checkbox.isChecked()
        verbose = self.verbose_checkbox.isChecked()

        # Validate inputs
        if not file_path.exists() or self.file_path.text() == "No file selected":
            self.log("Error: FormID list file not found")
            return

        if not db_path.parent.exists() or self.db_path.text() == "No database selected":
            self.log("Error: Database directory not found")
            return

        try:
            with sqlite3.connect(db_path) as conn:
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

                # Create table if it doesn't exist
                if not table_exists:
                    self.log(f"Creating table {game}...")
                    conn.execute(
                        f"""CREATE TABLE IF NOT EXISTS {game}
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        plugin TEXT, formid TEXT, entry TEXT)"""
                    )

                # Create index if it doesn't exist
                if not index_exists:
                    self.log(f"Creating index {game}_index...")
                    conn.execute(
                        f"CREATE INDEX IF NOT EXISTS {game}_index ON {game} (formid, plugin COLLATE nocase);"
                    )

                if conn.in_transaction:
                    conn.commit()

            # Now continue with the existing FormID processing
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
