import asyncio
from collections.abc import Callable
import multiprocessing
import multiprocessing.synchronize
import sys
import time
import traceback
import queue
import logging
from types import TracebackType
from typing import Literal

try:  # soundfile (specically its Numpy dependency) seem to cause virus alerts from some AV programs, including Windows Defender.
    import sounddevice as sdev
    import soundfile as sfile

    has_soundfile = True
except ImportError:
    has_soundfile = False
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import CLASSIC_Main as CMain
import CLASSIC_ScanGame as CGame
import CLASSIC_ScanLogs as CLogs


class PapyrusLogProcessor(QThread):
    # Signal to update the UI with new log messages
    new_log_messages = Signal(str)

    def __init__(self, result_queue: multiprocessing.Queue, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.result_queue = result_queue
        self.is_running = True  # Control flag to stop the thread

    def run(self) -> None:
        while self.is_running:
            messages = []
            try:
                while not self.result_queue.empty():
                    message = self.result_queue.get_nowait()
                    messages.append(message)
            except queue.Empty:
                pass

            if messages:
                # Join the messages and emit them to the main thread (for UI update)
                self.new_log_messages.emit("\n".join(messages))

            # Sleep for a bit to avoid hammering the CPU (you can adjust the interval)
            self.msleep(500)  # 500 ms, adjust as needed

    def stop(self) -> None:
        self.is_running = False


class ErrorDialog(QDialog):
    def __init__(self, error_text: str) -> None:
        super().__init__()
        self.setWindowTitle("Error")
        self.setMinimumSize(600, 400)
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(error_text)
        layout.addWidget(self.text_edit)

        copy_button = QPushButton("Copy to Clipboard", self)
        copy_button.clicked.connect(self.copy_to_clipboard)
        layout.addWidget(copy_button)

    def copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())


def show_exception_box(error_text: str) -> None:
    dialog = ErrorDialog(error_text)
    dialog.show()
    dialog.exec()


def custom_excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: TracebackType) -> None:
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(error_text)  # Still print to console
    show_exception_box(error_text)


sys.excepthook = custom_excepthook


def play_sound(sound_file: str) -> None:
    if has_soundfile:
        sound, samplerate = sfile.read(f"CLASSIC Data/sounds/{sound_file}")  # type: ignore
        sdev.play(sound, samplerate)  # type: ignore
        sdev.wait()  # type: ignore


def papyrus_worker(q: multiprocessing.Queue, stop_event: multiprocessing.synchronize.Event) -> None:
    while not stop_event.is_set():
        papyrus_result, _ = CGame.papyrus_logging()
        # Ensure the message starts and ends with newlines
        papyrus_result = f"\n{papyrus_result.strip()}\n"
        q.put(papyrus_result)
        time.sleep(5)  # Delay between checks


class OutputRedirector(QObject):
    outputWritten = Signal(str)

    def write(self, text: str) -> None:
        self.outputWritten.emit(str(text))

    def flush(self) -> None:
        pass


class CrashLogsScanWorker(QObject):
    finished = Signal()

    @Slot()
    def run(self) -> None:
        CLogs.crashlogs_scan()
        play_sound("classic_notify.wav")
        self.finished.emit()


class GameFilesScanWorker(QObject):
    finished = Signal()

    @Slot()
    def run(self) -> None:
        print(CGame.game_combined_result())
        print(CGame.mods_combined_result())
        CGame.write_combined_results()
        play_sound("classic_notify.wav")
        self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            f"Crash Log Auto Scanner & Setup Integrity Checker | {CMain.yaml_settings('CLASSIC Data/databases/CLASSIC Main.yaml', 'CLASSIC_Info.version')}"
        )
        self.setWindowIcon(QIcon("CLASSIC Data/graphics/CLASSIC.ico"))
        dark_style = """
        QWidget {
            background-color: #2b2b2b;
            color: #ffffff;
            font-family: "Segoe UI", sans-serif;
            font-size: 13px;
        }

        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QPushButton {
            background-color: #3c3c3c;
            border: 1px solid #5c5c5c;
            color: #ffffff;
        }

        QCheckBox::indicator:unchecked {
            image: url('unchecked.png');
        }

        QCheckBox::indicator:checked {
            image: url('checked.png');
        }

        QTabWidget::pane {
            border: 1px solid #444444;
        }

        QTabBar::tab {
            background-color: #3c3c3c;
            border: 1px solid #5c5c5c;
            color: #ffffff;
            padding: 5px;
        }

        QTabBar::tab:selected {
            background-color: #2b2b2b;
            color: #ffffff;
        }

        QPushButton {
            background-color: #3c3c3c;
            border: 1px solid #5c5c5c;
            color: #ffffff;
            padding: 5px;
        }

        QPushButton:hover {
            background-color: #444444;
        }

        QPushButton:pressed {
            background-color: #222222;
        }

        QLabel {
            color: #ffffff;
        }
    """
        self.setStyleSheet(dark_style)
        # self.setMinimumSize(700, 950)  # Increase minimum width from 650 to 700
        self.setFixedSize(700, 950)  # Set fixed size to prevent resizing, for now.

        # Set up the custom exception handler for the main window
        self.installEventFilter(self)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(10)

        self.tab_widget = QTabWidget()
        self.main_layout.addWidget(self.tab_widget)

        self.main_tab = QWidget()
        self.backups_tab = QWidget()
        self.tab_widget.addTab(self.main_tab, "MAIN OPTIONS")
        self.tab_widget.addTab(self.backups_tab, "FILE BACKUP")
        self.scan_button_group = QButtonGroup()
        self.setup_main_tab()
        self.setup_backups_tab()
        # In __init__ method, after setting up the main tab:
        self.initialize_folder_paths()
        self.setup_output_redirection()
        self.output_buffer = ""
        CMain.main_generate_required()
        # Perform initial update check
        if CMain.classic_settings("Update Check"):
            QTimer.singleShot(0, self.update_popup)

        self.update_check_timer = QTimer()
        self.update_check_timer.timeout.connect(self.perform_update_check)
        self.is_update_check_running = False

        # Set up Papyrus monitoring
        self.result_queue = multiprocessing.Queue()
        self.worker_stop_event = multiprocessing.Event()
        self.worker_process = None
        self.is_worker_running = False

        # Initialize thread attributes
        self.crash_logs_thread = None
        self.game_files_thread = None

        # Set up the QTimer for periodic updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_output_text_box_papyrus_watcher)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """if event.type() == QEvent.KeyPress:
                key_event = QKeyEvent(event)
                if key_event.key() == Qt.Key_F12:
                    # Simulate an exception when F12 is pressed (for testing)
                    raise Exception("This is a test exception")"""
        return super().eventFilter(watched, event)

    def update_popup(self) -> None:
        if not self.is_update_check_running:
            self.is_update_check_running = True
            self.update_check_timer.start(0)  # Start immediately

    def update_popup_explicit(self) -> None:
        self.update_check_timer.timeout.disconnect(self.perform_update_check)
        self.update_check_timer.timeout.connect(self.force_update_check)
        if not self.is_update_check_running:
            self.is_update_check_running = True
            self.update_check_timer.start(0)

    def perform_update_check(self) -> None:
        self.update_check_timer.stop()
        asyncio.run(self.async_update_check())

    def force_update_check(self) -> None:
        # Directly perform the update check without reading from settings
        self.is_update_check_running = True
        self.update_check_timer.stop()
        asyncio.run(self.async_update_check_explicit())  # Perform async check

    async def async_update_check(self) -> None:
        try:
            is_up_to_date = await CMain.classic_update_check(quiet=True)
            self.show_update_result(is_up_to_date)
        except Exception as e:
            self.show_update_error(str(e))
        finally:
            self.is_update_check_running = False
            self.update_check_timer.stop()  # Ensure the timer is always stopped

    async def async_update_check_explicit(self) -> None:
        try:
            is_up_to_date = await CMain.classic_update_check(
                quiet=True, gui_request=True
            )
            self.show_update_result(is_up_to_date)
        except Exception as e:
            self.show_update_error(str(e))
        finally:
            self.is_update_check_running = False
            self.update_check_timer.stop()  # Ensure the timer is always stopped

    def show_update_result(self, is_up_to_date: bool) -> None:
        if is_up_to_date:
            QMessageBox.information(
                self, "CLASSIC UPDATE", "You have the latest version of CLASSIC!"
            )
        else:
            update_popup_text: str = CMain.yaml_settings(
                "CLASSIC Data/databases/CLASSIC Main.yaml",
                "CLASSIC_Interface.update_popup_text",
            ) # type: ignore
            result = QMessageBox.question(
                self,
                "CLASSIC UPDATE",
                update_popup_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if result == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(
                    QUrl(
                        "https://github.com/evildarkarchon/CLASSIC-Fallout4/releases/latest"
                    )
                )

    def show_update_error(self, error_message: str) -> None:
        QMessageBox.warning(
            self, "Update Check Failed", f"Failed to check for updates: {error_message}"
        )

    def setup_main_tab(self) -> None:
        layout = QVBoxLayout(self.main_tab)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        # Top section
        self.mods_folder_edit = self.setup_folder_section(
            layout, "STAGING MODS FOLDER", "Box_SelectedMods", self.select_folder_mods
        )
        self.scan_folder_edit = self.setup_folder_section(
            layout, "CUSTOM SCAN FOLDER", "Box_SelectedScan", self.select_folder_scan
        )

        # Add first separator
        layout.addWidget(self.create_separator())

        # Main buttons section
        self.setup_main_buttons(layout)

        # Add second separator
        layout.addWidget(self.create_separator())

        # Checkbox section
        self.setup_checkboxes(layout)

        # Articles section
        self.setup_articles_section(layout)

        # Add a separator before bottom buttons
        layout.addWidget(self.create_separator())

        # Bottom buttons
        self.setup_bottom_buttons(layout)

        # Add output text box
        self.setup_output_text_box(layout)

        # Add some spacing
        layout.addSpacing(10)

        # Set the layout to be stretchable
        layout.setStretchFactor(self.output_text_box, 1)

    def setup_backups_tab(self) -> None:
        layout = QVBoxLayout(self.backups_tab)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        # Add explanation labels
        layout.addWidget(
            QLabel(
                "BACKUP > Backup files from the game folder into the CLASSIC Backup folder."
            )
        )
        layout.addWidget(
            QLabel(
                "RESTORE > Restore file backup from the CLASSIC Backup folder into the game folder."
            )
        )
        layout.addWidget(
            QLabel(
                "REMOVE > Remove files only from the game folder without removing existing backups."
            )
        )

        # Add separators and category buttons
        categories = ["XSE", "RESHADE", "VULKAN", "ENB"]
        for category in categories:
            layout.addWidget(self.create_separator())
            category_label = QLabel(category)
            category_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(category_label)

            button_layout = QHBoxLayout()

            backup_button = QPushButton(f"BACKUP {category}")
            backup_button.clicked.connect(
                lambda _, c=category: self.classic_files_manage(f"Backup {c}", "BACKUP")
            )
            button_layout.addWidget(backup_button)

            restore_button = QPushButton(f"RESTORE {category}")
            restore_button.clicked.connect(
                lambda _, c=category: self.classic_files_manage(
                    f"Backup {c}", "RESTORE"
                )
            )
            restore_button.setEnabled(False)  # Initially disabled
            setattr(
                self, f"RestoreButton_{category}", restore_button
            )  # Store reference to the button
            button_layout.addWidget(restore_button)

            remove_button = QPushButton(f"REMOVE {category}")
            remove_button.clicked.connect(
                lambda _, c=category: self.classic_files_manage(f"Backup {c}", "REMOVE")
            )
            button_layout.addWidget(remove_button)

            layout.addLayout(button_layout)

        # Check if backups exist and enable restore buttons accordingly
        self.check_existing_backups()

        # Add a button to open the backups folder
        open_backups_button = QPushButton("OPEN CLASSIC BACKUPS")
        open_backups_button.clicked.connect(self.open_backup_folder)
        layout.addWidget(open_backups_button)

    def check_existing_backups(self) -> None:
        for category in ["XSE", "RESHADE", "VULKAN", "ENB"]:
            backup_path = Path(f"CLASSIC Backup/Game Files/Backup {category}")
            if backup_path.is_dir() and any(backup_path.iterdir()):
                restore_button = getattr(self, f"RestoreButton_{category}", None)
                if restore_button:
                    restore_button.setEnabled(True)
                    restore_button.setStyleSheet(
                        """
                        QPushButton {
                            color: black;
                            background: rgb(250, 250, 250);
                            border-radius: 10px;
                            border: 2px solid black;
                        }
                    """
                    )

    def add_backup_section(self, layout: QBoxLayout, title: str, backup_type: Literal["XSE", "RESHADE", "VULKAN", "ENB"]) -> None:
        layout.addWidget(self.create_separator())

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        buttons_layout = QHBoxLayout()
        backup_button = QPushButton(f"BACKUP {backup_type}")
        restore_button = QPushButton(f"RESTORE {backup_type}")
        remove_button = QPushButton(f"REMOVE {backup_type}")

        for button, action in [
            (backup_button, "BACKUP"),
            (restore_button, "RESTORE"),
            (remove_button, "REMOVE"),
        ]:
            button.clicked.connect(
                lambda _, b=backup_type, a=action: self.classic_files_manage(
                    f"Backup {b}", a  # type: ignore
                )
            )
            button.setStyleSheet(
                """
                QPushButton {
                    color: white;
                    background: rgba(10, 10, 10, 0.75);
                    border-radius: 10px;
                    border: 1px solid white;
                    font-size: 11px;
                    min-height: 48px;
                    max-height: 48px;
                    min-width: 180px;
                    max-width: 180px;
                }
            """
            )
            buttons_layout.addWidget(button)

        layout.addLayout(buttons_layout)

    def classic_files_manage(self, selected_list: str, selected_mode: Literal["BACKUP", "RESTORE", "REMOVE"] = "BACKUP") -> None:
        list_name = selected_list.split(" ", 1)
        try:
            CGame.game_files_manage(selected_list, selected_mode)
            if selected_mode == "BACKUP":
                # Enable the corresponding restore button
                restore_button = getattr(self, f"RestoreButton_{list_name[1]}", None)
                if restore_button:
                    restore_button.setEnabled(True)
                    restore_button.setStyleSheet(
                        """
                        QPushButton {
                            color: black;
                            background: rgb(250, 250, 250);
                            border-radius: 10px;
                            border: 2px solid black;
                        }
                    """
                    )
        except PermissionError:
            QMessageBox.critical(
                self,
                "Error",
                "Unable to access files from your game folder. Please run CLASSIC in admin mode to resolve this problem.",
            )

    def help_popup_backup(self) -> None:
        help_popup_text: str = CMain.yaml_settings(
            "CLASSIC Data/databases/CLASSIC Main.yaml",
            "CLASSIC_Interface.help_popup_backup",
        ) # type: ignore
        QMessageBox.information(self, "NEED HELP?", help_popup_text)

    @staticmethod
    def open_backup_folder() -> None:
        backup_path = Path.cwd() / "CLASSIC Backup/Game Files"
        QDesktopServices.openUrl(QUrl.fromLocalFile(backup_path))

    def setup_output_text_box(self, layout: QLayout) -> None:
        self.output_text_box = QTextEdit(self)
        self.output_text_box.setReadOnly(True)
        self.output_text_box.setStyleSheet(
            """
            QTextEdit {
                color: white;
                font-family: "Cascadia Mono", Consolas, monospace;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 13px;
            }
        """
        )  # Have to use alternate font here because the default font doesn't support some characters.

        self.output_text_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.output_text_box.setMinimumHeight(150)
        layout.addWidget(self.output_text_box)

        self.output_buffer = ""

    def update_output_text_box(self, text: str | bytes) -> None:
        try:
            # If the incoming text is bytes, decode it
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            else:
                text = str(text)

            # Append the incoming text to the buffer
            self.output_buffer += text

            # Split the buffer into lines, keeping newlines
            lines = self.output_buffer.splitlines(True)

            # Initialize flag to track if the last line ended with a newline
            ends_with_newline = self.output_buffer.endswith("\n")

            # Process all complete lines
            complete_lines = lines[:-1] if not ends_with_newline else lines

            if complete_lines:
                current_text = self.output_text_box.toPlainText()

                # Append complete lines without extra newlines
                new_text = current_text + "".join(complete_lines)
                self.output_text_box.setPlainText(new_text)

                # Scroll to the bottom
                scrollbar = self.output_text_box.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

            # Keep the last incomplete line in the buffer if it's not complete
            self.output_buffer = lines[-1] if not ends_with_newline else ""

        except Exception as e:
            print(f"Error in update_output_text_box: {e}")

    def process_lines(self, lines: list[str]) -> None:
        for line in lines:
            stripped_line = line.rstrip()
            if stripped_line or line.endswith("\n"):
                self.output_text_box.append(stripped_line)

        # Scroll to the bottom of the text box
        scrollbar = self.output_text_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def setup_output_redirection(self) -> None:
        self.output_redirector = OutputRedirector()
        self.output_redirector.outputWritten.connect(self.update_output_text_box)
        sys.stdout = self.output_redirector
        sys.stderr = self.output_redirector  # Redirect stderr as well

    @staticmethod
    def create_separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

    def setup_checkboxes(self, layout: QBoxLayout) -> None:
        checkbox_layout = QVBoxLayout()

        # Title for the checkbox section
        title_label = QLabel("CLASSIC SETTINGS")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        checkbox_layout.addWidget(title_label)

        # Grid for checkboxes
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(40)  # Increased spacing
        grid_layout.setVerticalSpacing(20)  # Increased spacing

        checkboxes = [
            ("FCX MODE", "FCX Mode"),
            ("SIMPLIFY LOGS", "Simplify Logs"),
            ("UPDATE CHECK", "Update Check"),
            ("VR MODE", "VR Mode"),
            ("SHOW FID VALUES", "Show FormID Values"),
            ("MOVE INVALID LOGS", "Move Unsolved Logs"),
        ]

        for index, (label, setting) in enumerate(checkboxes):
            checkbox = self.create_checkbox(label, setting)
            row = index // 3
            col = index % 3
            grid_layout.addWidget(checkbox, row, col, Qt.AlignmentFlag.AlignLeft)

        checkbox_layout.addLayout(grid_layout)

        # Add some vertical spacing
        checkbox_layout.addSpacing(20)

        layout.addLayout(checkbox_layout)

        # Add a separator after the checkboxes
        layout.addWidget(self.create_separator())

    @staticmethod
    def create_checkbox(label_text: str, setting: str) -> QCheckBox:
        checkbox = QCheckBox(label_text)
        checkbox.setChecked(CMain.classic_settings(setting)) # type: ignore
        checkbox.stateChanged.connect(
            lambda state: CMain.yaml_settings(
                "CLASSIC Settings.yaml", f"CLASSIC_Settings.{setting}", bool(state) # type: ignore
            )
        )

        # Apply custom style sheet
        checkbox.setStyleSheet(
            """
            QCheckBox {
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
            QCheckBox::indicator:unchecked {
                image: url(CLASSIC Data/graphics/unchecked.png);
            }
            QCheckBox::indicator:checked {
                image: url(CLASSIC Data/graphics/checked.png);
            }
        """
        )

        return checkbox

    @staticmethod
    def setup_folder_section(layout: QBoxLayout, title: str, box_name: str, browse_callback: Callable[[], None], tooltip: str = "") -> QLineEdit:
        section_layout = QHBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(5)

        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setFixedWidth(180)
        section_layout.addWidget(label)

        line_edit = QLineEdit()
        line_edit.setObjectName(box_name)
        section_layout.addWidget(line_edit, 1)

        browse_button = QPushButton("Browse Folder")
        if tooltip:
            browse_button.setToolTip(tooltip)
        browse_button.clicked.connect(browse_callback)
        section_layout.addWidget(browse_button)

        layout.addLayout(section_layout)
        return line_edit  # Return the created QLineEdit

    def setup_main_buttons(self, layout: QBoxLayout) -> None:
        # Main action buttons
        main_buttons_layout = QHBoxLayout()
        main_buttons_layout.setSpacing(10)
        self.crash_logs_button = self.add_main_button(
            main_buttons_layout, "SCAN CRASH LOGS", self.crash_logs_scan
        )
        self.scan_button_group.addButton(self.crash_logs_button)
        self.game_files_button = self.add_main_button(
            main_buttons_layout, "SCAN GAME FILES", self.game_files_scan
        )
        self.scan_button_group.addButton(self.game_files_button)
        layout.addLayout(main_buttons_layout)

        # Bottom row buttons
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.setSpacing(5)
        self.add_bottom_button(
            bottom_buttons_layout, "CHANGE INI PATH", self.select_folder_ini
        )
        self.add_bottom_button(
            bottom_buttons_layout, "OPEN CLASSIC SETTINGS", self.open_settings
        )
        self.add_bottom_button(
            bottom_buttons_layout, "CHECK UPDATES", self.update_popup_explicit
        )
        layout.addLayout(bottom_buttons_layout)

    @staticmethod
    def setup_articles_section(layout: QBoxLayout) -> None:
        # Title for the articles section
        title_label = QLabel("ARTICLES / WEBSITES / NEXUS LINKS")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        # Grid layout for article buttons
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(10)
        grid_layout.setVerticalSpacing(10)

        button_data = [
            {
                "text": "BUFFOUT 4 INSTALLATION",
                "url": "https://www.nexusmods.com/fallout4/articles/3115",
            },
            {
                "text": "FALLOUT 4 SETUP TIPS",
                "url": "https://www.nexusmods.com/fallout4/articles/4141",
            },
            {
                "text": "IMPORTANT PATCHES LIST",
                "url": "https://www.nexusmods.com/fallout4/articles/3769",
            },
            {
                "text": "BUFFOUT 4 NEXUS PAGE",
                "url": "https://www.nexusmods.com/fallout4/mods/47359",
            },
            {
                "text": "CLASSIC NEXUS PAGE",
                "url": "https://www.nexusmods.com/fallout4/mods/56255",
            },
            {
                "text": "CLASSIC GITHUB",
                "url": "https://github.com/GuidanceOfGrace/CLASSIC-Fallout4",
            },
            {
                "text": "DDS TEXTURE SCANNER",
                "url": "https://www.nexusmods.com/fallout4/mods/71588",
            },
            {"text": "BETHINI PIE", "url": "https://www.nexusmods.com/site/mods/631"},
            {
                "text": "WRYE BASH TOOL",
                "url": "https://www.nexusmods.com/fallout4/mods/20032",
            },
        ]

        for i, data in enumerate(button_data):
            button = QPushButton(data["text"])
            button.setFixedSize(180, 50)  # Set fixed size for buttons
            button.setStyleSheet(
                """
                QPushButton {
                    color: white;
                    background-color: rgba(10, 10, 10, 0.75);
                    border: 1px solid white;
                    border-radius: 5px;
                    padding: 5px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(50, 50, 50, 0.75);
                }
                QPushButton:disabled {
                    color: gray;
                    background-color: rgba(10, 10, 10, 0.75);
                }
            """
            )
            button.clicked.connect(
                lambda _, url=data["url"]: QDesktopServices.openUrl(QUrl(url))
            )
            row = i // 3
            col = i % 3
            grid_layout.addWidget(button, row, col, Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(grid_layout)

        # Add some vertical spacing after the articles section
        layout.addSpacing(20)

    def setup_bottom_buttons(self, layout: QBoxLayout) -> None:
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(5)

        # ABOUT button
        about_button = QPushButton("ABOUT")
        about_button.setFixedSize(80, 30)
        about_button.clicked.connect(self.show_about)
        about_button.setStyleSheet(
            """
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """
        )
        bottom_layout.addWidget(about_button)

        # HELP button
        help_button = QPushButton("HELP")
        help_button.setFixedSize(80, 30)
        help_button.clicked.connect(self.help_popup_main)
        help_button.setStyleSheet(
            """
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """
        )
        bottom_layout.addWidget(help_button)

        # PAPYRUS MONITORING button
        self.papyrus_button = QPushButton("START PAPYRUS MONITORING")
        self.papyrus_button.setFixedHeight(30)
        self.papyrus_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.papyrus_button.clicked.connect(self.toggle_papyrus_worker)
        self.papyrus_button.setStyleSheet(
            """
            QPushButton {
                color: black;
                background: rgb(45, 237, 138);
                border-radius: 10px;
                border: 1px solid black;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:disabled {
                color: gray;
                background: rgba(10, 10, 10, 0.75);
            }
        """
        )
        self.papyrus_button.setToolTip(
            "Start monitoring the Papyrus logs for new errors."
        )
        self.papyrus_button.setCheckable(True)
        # self.papyrus_button.setEnabled(False) # Temporarily disabled until the feature is fully implemented.
        bottom_layout.addWidget(self.papyrus_button)

        # EXIT button
        exit_button = QPushButton("EXIT")
        exit_button.setFixedSize(80, 30)
        exit_button.clicked.connect(QApplication.quit)
        exit_button.setStyleSheet(
            """
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """
        )
        bottom_layout.addWidget(exit_button)

        layout.addLayout(bottom_layout)

    def show_about(self) -> None:
        about_text = (
            "Crash Log Auto Scanner & Setup Integrity Checker\n\n"
            "Made by: Poet\n"
            "Contributors: evildarkarchon | kittivelae | AtomicFallout757"
        )
        QMessageBox.about(self, "About CLASSIC", about_text)

    def help_popup_main(self) -> None:
        help_popup_text: str = CMain.yaml_settings(
            "CLASSIC Data/databases/CLASSIC Main.yaml",
            "CLASSIC_Interface.help_popup_main",
        ) # type: ignore
        QMessageBox.information(self, "NEED HELP?", help_popup_text)

    @staticmethod
    def add_main_button(layout: QLayout, text: str, callback: Callable[[], None], tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setStyleSheet(
            """
            QPushButton {
                color: black;
                background: rgba(250, 250, 250, 0.90);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 17px;
                font-weight: bold;  /* Add this line to make the text bold */
                min-height: 48px;
                max-height: 48px;
            }
            QPushButton:disabled {
                color: gray;
                background-color: rgba(10, 10, 10, 0.75);
            }
        """
        )
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def add_bottom_button(layout: QLayout, text: str, callback: Callable[[], None], tooltip: str = "") -> None:
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setStyleSheet(
            """
            color: white;
            background: rgba(10, 10, 10, 0.75);
            border-radius: 10px;
            border: 1px solid white;
            font-size: 11px;
            min-height: 32px;
            max-height: 32px;
        """
        )
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def select_folder_scan(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Custom Scan Folder")
        if folder:
            self.scan_folder_edit.setText(folder)
            CMain.yaml_settings(
                "CLASSIC Settings.yaml", "CLASSIC_Settings.SCAN Custom Path", folder
            )

    def select_folder_mods(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Staging Mods Folder")
        if folder:
            self.mods_folder_edit.setText(folder)
            CMain.yaml_settings(
                "CLASSIC Settings.yaml", "CLASSIC_Settings.MODS Folder Path", folder
            )

    def initialize_folder_paths(self) -> None:
        scan_folder: str = CMain.classic_settings("SCAN Custom Path") # type: ignore
        mods_folder: str = CMain.classic_settings("MODS Folder Path") # type: ignore

        if scan_folder:
            self.scan_folder_edit.setText(scan_folder)
        if mods_folder:
            self.mods_folder_edit.setText(mods_folder)

    def select_folder_ini(self) -> None:
        folder = QFileDialog.getExistingDirectory(self)
        if folder:
            CMain.yaml_settings(
                "CLASSIC Settings.yaml", "CLASSIC_Settings.INI Folder Path", folder
            )
            QMessageBox.information(
                self, "New INI Path Set", f"You have set the new path to: \n{folder}"
            )

    @staticmethod
    def open_settings() -> None:
        settings_file = "CLASSIC Settings.yaml"
        QDesktopServices.openUrl(QUrl.fromLocalFile(settings_file))

    def crash_logs_scan(self) -> None:
        if self.crash_logs_thread is None:
            self.crash_logs_thread = QThread()
            self.crash_logs_worker = CrashLogsScanWorker()
            self.crash_logs_worker.moveToThread(self.crash_logs_thread)
            self.crash_logs_thread.started.connect(self.crash_logs_worker.run)
            self.crash_logs_worker.finished.connect(self.crash_logs_thread.quit)
            self.crash_logs_worker.finished.connect(self.crash_logs_worker.deleteLater)
            self.crash_logs_thread.finished.connect(self.crash_logs_thread.deleteLater)
            self.crash_logs_thread.finished.connect(self.crash_logs_scan_finished)

            # Disable buttons and update text
            self.disable_scan_buttons()

            self.crash_logs_thread.start()

    def game_files_scan(self) -> None:
        if self.game_files_thread is None:
            self.game_files_thread = QThread()
            self.game_files_worker = GameFilesScanWorker()
            self.game_files_worker.moveToThread(self.game_files_thread)
            self.game_files_thread.started.connect(self.game_files_worker.run)
            self.game_files_worker.finished.connect(self.game_files_thread.quit)
            self.game_files_worker.finished.connect(self.game_files_worker.deleteLater)
            self.game_files_thread.finished.connect(self.game_files_thread.deleteLater)
            self.game_files_thread.finished.connect(self.game_files_scan_finished)

            # Disable buttons and update text
            self.disable_scan_buttons()

            self.game_files_thread.start()

    def disable_scan_buttons(self) -> None:
        for button_id in self.scan_button_group.buttons():
            button_id.setEnabled(False)

    def enable_scan_buttons(self) -> None:
        for button_id in self.scan_button_group.buttons():
            button_id.setEnabled(True)

    def crash_logs_scan_finished(self) -> None:
        self.crash_logs_thread = None
        self.enable_scan_buttons()

    def game_files_scan_finished(self) -> None:
        self.game_files_thread = None
        self.enable_scan_buttons()

    def toggle_papyrus_worker(self) -> None:
        if not self.is_worker_running:
            # Start the Papyrus log processor thread
            self.log_processor = PapyrusLogProcessor(self.result_queue)
            self.log_processor.new_log_messages.connect(self.update_output_text_box)
            self.log_processor.start()

            # Start the worker process for papyrus logs
            self.worker_stop_event = multiprocessing.Event()
            self.worker_process = multiprocessing.Process(
                target=papyrus_worker, args=(self.result_queue, self.worker_stop_event)
            )
            self.worker_process.daemon = True
            self.worker_process.start()

            # Start the timer for periodic updates
            self.timer.start(5000)  # Update every 5 seconds

            # Update button state and style
            self.papyrus_button.setText("STOP PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet(
                """
                QPushButton {
                    color: black;
                    background: rgb(240, 63, 40);  /* Red when monitoring is active */
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                    font-size: 14px;
                }
            """
            )
            self.is_worker_running = True
        else:
            # Stop the worker process and the thread
            self.worker_stop_event.set()  # Stop the multiprocessing worker
            if self.worker_process:
                self.worker_process.join()  # Ensure the worker process ends

            # Stop the log processor thread
            if self.log_processor:
                self.log_processor.stop()
                self.log_processor.wait()  # Wait for the thread to stop

            # Stop the timer
            self.timer.stop()

            # Update button state and style
            self.papyrus_button.setText("START PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet(
                """
                QPushButton {
                    color: black;
                    background: rgb(45, 237, 138);  /* Green when monitoring is off */
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                    font-size: 14px;
                }
            """
            )
            self.is_worker_running = False

    def update_output_text_box_papyrus_watcher(self) -> None:
        if not hasattr(self, "message_buffer"):
            self.message_buffer = ""

        try:
            while not self.result_queue.empty():
                message = self.result_queue.get_nowait()
                self.message_buffer += message

            # Process the buffer if it contains complete Papyrus data
            if (
                "NUMBER OF DUMPS" in self.message_buffer
                and "NUMBER OF ERRORS" in self.message_buffer
            ):
                # Split the buffer into lines
                lines = self.message_buffer.split("\n")
                papyrus_data = []
                non_papyrus_data = []

                # Separate Papyrus monitoring data from other data
                for line in lines:
                    if any(
                        key in line
                        for key in [
                            "NUMBER OF DUMPS",
                            "NUMBER OF STACKS",
                            "DUMPS/STACKS RATIO",
                            "NUMBER OF WARNINGS",
                            "NUMBER OF ERRORS",
                        ]
                    ):
                        papyrus_data.append(line.strip())
                    elif line.strip():
                        non_papyrus_data.append(line)

                # Update the text box with Papyrus data
                if papyrus_data:
                    current_text = self.output_text_box.toPlainText()
                    current_lines = current_text.split("\n")

                    # Find the Papyrus monitoring section
                    papyrus_start = -1
                    papyrus_end = -1
                    for i, line in enumerate(current_lines):
                        if "NUMBER OF DUMPS" in line:
                            papyrus_start = i
                        if papyrus_start != -1 and "NUMBER OF ERRORS" in line:
                            papyrus_end = i + 1
                            break

                    # Update or add the Papyrus monitoring section
                    if papyrus_start != -1 and papyrus_end != -1:
                        updated_lines = (
                            current_lines[:papyrus_start]
                            + papyrus_data
                            + current_lines[papyrus_end:]
                        )
                    else:
                        updated_lines = (
                            current_lines
                            + ["\n--- Papyrus Monitoring ---"]
                            + papyrus_data
                        )

                    new_text = "\n".join(updated_lines)
                    self.output_text_box.setPlainText(new_text)

                # Append any non-Papyrus data
                if non_papyrus_data:
                    self.output_text_box.append("\n".join(non_papyrus_data))

                # Clear the processed data from the buffer
                self.message_buffer = self.message_buffer.split("NUMBER OF ERRORS")[-1]

                # Scroll to the bottom of the text box
                scrollbar = self.output_text_box.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

        except queue.Empty:
            pass  # No messages to process, continue


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)

    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception as _:
        error_text = traceback.format_exc()
        show_exception_box(error_text)
