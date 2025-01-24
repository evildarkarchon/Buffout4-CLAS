import asyncio
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Literal

import regex as re
from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFontMetrics, QIcon, QPixmap
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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


@dataclass
class PapyrusStats:
    """Data class to hold Papyrus log statistics"""
    timestamp: datetime
    dumps: int
    stacks: int
    warnings: int
    errors: int
    ratio: float

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PapyrusStats):
            return NotImplemented
        return (self.dumps == other.dumps and
                self.stacks == other.stacks and
                self.warnings == other.warnings and
                self.errors == other.errors)

class PapyrusMonitorWorker(QObject):
    """Worker class to monitor Papyrus logs in a separate thread"""

    # Signal when new stats are available
    statsUpdated = Signal(PapyrusStats)

    # Signal for errors
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._should_run = True
        self._last_stats: PapyrusStats | None = None
        self.error_sound_played = False  # Track if error sound has played this session

    def stop(self) -> None:
        """Stop the monitoring loop"""
        self._should_run = False

    @Slot()
    def run(self) -> None:
        """Main monitoring loop"""
        while self._should_run:
            try:
                message, count = CGame.papyrus_logging()

                # Parse the message to extract stats
                current_stats = self._parse_stats(message, count)

                # Only emit if stats have changed
                if self._last_stats != current_stats:
                    self.statsUpdated.emit(current_stats)
                    self._last_stats = current_stats

                # Sleep for a short interval to prevent excessive CPU usage
                QThread.msleep(1000)  # Check every second

            except (OSError, ValueError) as e:
                self.error.emit(str(e))
                break

    @staticmethod
    def _parse_stats(message: str, dump_count: int) -> PapyrusStats:
        """Parse the papyrus log message into statistics"""
        stats = {
            'dumps': dump_count,
            'stacks': 0,
            'warnings': 0,
            'errors': 0
        }

        for line in message.splitlines():
            if ': ' in line:
                key, value = line.split(': ')
                key = key.strip().lower()
                if key == 'number of stacks':
                    stats['stacks'] = int(value)
                elif key == 'number of warnings':
                    stats['warnings'] = int(value)
                elif key == 'number of errors':
                    stats['errors'] = int(value)

        ratio = 0.0 if stats['dumps'] == 0 else stats['dumps'] / stats['stacks']

        return PapyrusStats(
            timestamp=datetime.now(),
            dumps=stats['dumps'],
            stacks=stats['stacks'],
            warnings=stats['warnings'],
            errors=stats['errors'],
            ratio=ratio
        )

# Example fix for pastebin fetch
class PastebinFetchWorker(QObject):
    finished = Signal()
    error = Signal(str)
    success = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    @Slot()
    def run(self) -> None:
        try:
            CLogs.pastebin_fetch(self.url)
            self.success.emit(self.url)
        except (OSError, ValueError) as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

class CustomAboutDialog(QDialog):
    def __init__(self, parent: QMainWindow | QDialog | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setFixedSize(600, 200)  # Adjust size for icon and text

        # Create a layout with margins similar to QMessageBox.about
        layout: QVBoxLayout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)  # Adjust margins (left, top, right, bottom)

        # Horizontal layout for icon and text
        h_layout: QHBoxLayout = QHBoxLayout()

        # Add the icon
        icon_label: QLabel = QLabel(self)
        icon: QIcon = QIcon("CLASSIC Data/graphics/CLASSIC.ico")
        pixmap: QPixmap = icon.pixmap(128, 128)  # Request the 64x64 icon size
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)  # Align icon at the top
        h_layout.addWidget(icon_label)

        # Add the text next to the icon
        text_label: QLabel = QLabel(
            "Crash Log Auto Scanner & Setup Integrity Checker\n\n"
            "Made by: Poet\n"
            "Contributors: evildarkarchon | kittivelae | AtomicFallout757 | wxMichael"
        )
        text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)  # Align text to top-left
        text_label.setWordWrap(True)  # Allow text wrapping for better formatting
        h_layout.addWidget(text_label)

        layout.addLayout(h_layout)

        # Add a Close button at the bottom
        close_button: QPushButton = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        # Align the Close button to the right and add some space at the bottom
        layout.setAlignment(close_button, Qt.AlignmentFlag.AlignRight)

class ErrorDialog(QDialog):
    def __init__(self, error_dialog_text: str) -> None:
        super().__init__()
        self.setWindowTitle("Error")
        self.setMinimumSize(600, 300)
        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(error_dialog_text)
        layout.addWidget(self.text_edit)

        copy_button = QPushButton("Copy to Clipboard", self)
        copy_button.clicked.connect(self.copy_to_clipboard)
        layout.addWidget(copy_button)

    def copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self.text_edit.toPlainText())


def show_exception_box(exception_text: str) -> None:
    dialog = ErrorDialog(exception_text)
    dialog.show()
    dialog.exec()


def custom_excepthook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: TracebackType | None) -> None:
    custom_except_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(custom_except_text)  # Still print to console
    show_exception_box(custom_except_text)


sys.excepthook = custom_excepthook

import CLASSIC_Main as CMain  # noqa: E402
import CLASSIC_ScanGame as CGame  # noqa: E402
import CLASSIC_ScanLogs as CLogs  # noqa: E402


class AudioPlayer(QObject):
    # Define signals for different sounds
    play_error_signal = Signal()
    play_notify_signal = Signal()
    play_custom_signal = Signal(str)  # Signal to play a custom sound with a path

    def __init__(self) -> None:
        super().__init__()
        self.audio_enabled = CMain.classic_settings(bool, "Audio Notifications")
        if self.audio_enabled is None:
            CMain.yaml_settings(bool, CMain.YAML.Settings, "CLASSIC_Settings.Audio Notifications", True)
            self.audio_enabled = True

        # Setup QSoundEffect objects for the preset sounds
        self.error_sound = QSoundEffect()
        self.error_sound.setSource(QUrl.fromLocalFile("CLASSIC Data/sounds/classic_error.wav"))
        self.error_sound.setVolume(1.0)  # Set max volume

        self.notify_sound = QSoundEffect()
        self.notify_sound.setSource(QUrl.fromLocalFile("CLASSIC Data/sounds/classic_notify.wav"))
        self.notify_sound.setVolume(1.0)  # Set max volume

        # Connect signals to respective slots
        if self.audio_enabled:
            self.play_error_signal.connect(self.play_error_sound)
            self.play_notify_signal.connect(self.play_notify_sound)
            self.play_custom_signal.connect(lambda file: self.play_custom_sound(file))  # Use custom path

    def play_error_sound(self) -> None:
        if self.audio_enabled and self.error_sound.isLoaded():
            self.error_sound.play()

    def play_notify_sound(self) -> None:
        if self.audio_enabled and self.notify_sound.isLoaded():
            self.notify_sound.play()

    @staticmethod
    def play_custom_sound(sound_path: str) -> None:
        custom_sound = QSoundEffect()
        custom_sound.setSource(QUrl.fromLocalFile(sound_path))
        custom_sound.setVolume(1.0)
        custom_sound.play()

    def toggle_audio(self, state: bool) -> None:
        self.audio_enabled = state
        if not state:
            self.play_notify_signal.disconnect()
            self.play_error_signal.disconnect()
            self.play_custom_signal.disconnect()
        else:
            self.play_notify_signal.connect(self.play_notify_sound)
            self.play_error_signal.connect(self.play_error_sound)
            self.play_custom_signal.connect(lambda file: self.play_custom_sound(file))

class ManualPathDialog(QDialog):
    def __init__(self, parent: QMainWindow | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set INI Files Directory")
        self.setFixedSize(700, 150)

        # Create layout and input field
        layout = QVBoxLayout(self)

        # Add a label
        label = QLabel(f"Enter the path for the {CMain.gamevars["game"]} INI files directory (Example: c:\\users\\<name>\\Documents\\My Games\\{CMain.gamevars["game"]})", self)
        layout.addWidget(label)

        inputlayout = QHBoxLayout()
        self.input_field = QLineEdit(self)
        self.input_field.setPlaceholderText("Enter the INI directory or click 'Browse'...")
        inputlayout.addWidget(self.input_field)

        # Create the "Browse" button
        browse_button = QPushButton("Browse...", self)
        browse_button.clicked.connect(self.browse_directory)
        inputlayout.addWidget(browse_button)
        layout.addLayout(inputlayout)

        # Create standard OK button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_directory(self) -> None:
        # Open directory browser and update the input field
        manual_path = QFileDialog.getExistingDirectory(self, "Select Directory for INI Files")
        if manual_path:
            self.input_field.setText(manual_path)

    def get_path(self) -> str:
        return self.input_field.text()

class GamePathDialog(QDialog):
    def __init__(self, parent: QMainWindow | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set INI Files Directory")
        self.setFixedSize(700, 150)

        # Create layout and input field
        layout = QVBoxLayout(self)

        # Add a label
        label = QLabel(f"Enter the path for the {CMain.gamevars["game"]} directory (example: C:\\Steam\\steamapps\\common\\{CMain.gamevars["game"]})", self)
        layout.addWidget(label)

        inputlayout = QHBoxLayout()
        self.input_field = QLineEdit(self)
        self.input_field.setPlaceholderText("Enter the Game's directory or click 'Browse'...")
        inputlayout.addWidget(self.input_field)

        # Create the "Browse" button
        browse_button = QPushButton("Browse...", self)
        browse_button.clicked.connect(self.browse_directory)
        inputlayout.addWidget(browse_button)
        layout.addLayout(inputlayout)

        # Create standard OK button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_directory(self) -> None:
        # Open directory browser and update the input field
        manual_path = QFileDialog.getExistingDirectory(self, f"Select Directory for {CMain.gamevars["game"]}")
        if manual_path:
            self.input_field.setText(manual_path)

    def get_path(self) -> str:
        return self.input_field.text()

class OutputRedirector(QObject):
    outputWritten = Signal(str)

    def write(self, text: str) -> None:
        self.outputWritten.emit(str(text))

    def flush(self) -> None:
        pass


class CrashLogsScanWorker(QObject):
    finished = Signal()
    notify_sound_signal = Signal()
    error_sound_signal = Signal()
    custom_sound_signal = Signal(str)  # In case a custom sound needs to be played

    @Slot()
    def run(self) -> None:
        # Here you can determine the appropriate sound to play.
        # For simplicity, we're triggering the notify sound when the scan completes.
        try:
            CLogs.crashlogs_scan()
            self.notify_sound_signal.emit()  # Emit signal to play notify sound
        except Exception as e:  # noqa: BLE001
            if CMain.classic_settings(bool, "Audio Notifications"):
                self.error_sound_signal.emit()  # Emit signal to play error sound in case of exception
            else:
                ErrorDialog(str(e)).exec()
        finally:
            self.finished.emit()


class GameFilesScanWorker(QObject):
    finished = Signal()
    notify_sound_signal = Signal()
    error_sound_signal = Signal()
    custom_sound_signal = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            CGame.write_combined_results()
            self.notify_sound_signal.emit()  # Emit signal to play notify sound
        except Exception as e:  # noqa: BLE001
            if CMain.classic_settings(bool, "Audio Notifications"):
                self.error_sound_signal.emit()  # Emit signal to play error sound in case of exception
            else:
                ErrorDialog(str(e)).exec()
        finally:
            self.finished.emit()



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.game_files_worker = None
        self.crash_logs_worker = None
        self.papyrus_button = None
        self.game_files_button = None
        self.crash_logs_button = None
        self.output_redirector = None
        self.output_text_box = None
        self.scan_folder_edit = None
        self.mods_folder_edit = None
        self.pastebin_fetch_button = None
        self.pastebin_id_input = None
        self.pastebin_label = None
        self.papyrus_monitor_thread: QThread | None = None
        self.papyrus_monitor_worker: PapyrusMonitorWorker | None = None
        self._last_stats: PapyrusStats | None = None
        self.pastebin_url_regex: re.Pattern = re.compile(r"^https?://pastebin\.com/(\w+)$")

        CMain.initialize(is_gui=True)

        self.setWindowTitle(
            f"Crash Log Auto Scanner & Setup Integrity Checker | {CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Info.version")}"
        )
        self.setWindowIcon(QIcon("CLASSIC Data/graphics/CLASSIC.ico"))
        dark_style = """
QWidget {
    background-color: #2b2b2b;
    color: #ffffff;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #5c5c5c;
    color: #ffffff;
}

/* ComboBox Styling */
QComboBox {
    background-color: #3c3c3c;
    border: 1px solid #5c5c5c;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
    color: #ffffff;
}

QComboBox:hover {
    background-color: #444444;
    border-color: #666666;
}

QComboBox:focus {
    border-color: #0078d4;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: pb_source(CLASSIC Data/graphics/arrow-down.svg);
    width: 12px;
    height: 12px;
}

QComboBox:disabled {
    background-color: #2b2b2b;
    color: #666666;
}

/* ScrollBar Styling */
QScrollBar:vertical {
    background-color: #202020;
    width: 14px;
    border: none;
    border-radius: 7px;
    margin: 0;
}

QScrollBar::groove:vertical {
    background-color: #202020;
    border: none;
    border-radius: 7px;
}

QScrollBar::handle:vertical {
    background-color: #686868;
    min-height: 30px;
    border-radius: 5px;
    margin: 2px 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #7f7f7f;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: #202020;
    border: none;
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #202020;
    height: 14px;
    border: none;
    border-radius: 7px;
    margin: 0;
}

QScrollBar::groove:horizontal {
    background-color: #202020;
    border: none;
    border-radius: 7px;
}

QScrollBar::handle:horizontal {
    background-color: #686868;
    min-width: 30px;
    border-radius: 5px;
    margin: 2px 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #7f7f7f;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: #202020;
    border: none;
    width: 0px;
}

QScrollBar::corner {
    background: #202020;
}

/* Tab Widget Styling */
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

/* Button Styling */
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

/* Label Styling */
QLabel {
    color: #ffffff;
}
    """
        self.setStyleSheet(dark_style)
        # self.setMinimumSize(700, 950)  # Increase minimum width from 650 to 700
        self.setFixedSize(700, 950)  # Set fixed size to prevent resizing, for now.

        # Set up the custom exception handler for the main window
        self.installEventFilter(self)

        self.audio_player = AudioPlayer()

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
        if CMain.classic_settings(bool, "Update Check"):
            QTimer.singleShot(0, self.update_popup)

        self.update_check_timer = QTimer()
        self.update_check_timer.timeout.connect(self.perform_update_check)
        self.is_update_check_running = False

        # Initialize thread attributes
        self.crash_logs_thread: QThread | None = None
        self.game_files_thread: QThread | None = None

        if CMain.manual_docs_gui is None or CMain.game_path_gui is None:
            raise TypeError("CMain not initialized")
        CMain.manual_docs_gui.manual_docs_path_signal.connect(self.show_manual_docs_path_dialog)
        CMain.game_path_gui.game_path_signal.connect(self.show_game_path_dialog)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """if event.type() == QEvent.KeyPress:
                key_event = QKeyEvent(event)
                if key_event.key() == Qt.Key_F12:
                    # Simulate an exception when F12 is pressed (for testing)
                    raise Exception("This is a test exception")"""
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop the Papyrus monitor thread when the window is closed"""
        self.stop_papyrus_monitoring()
        super().closeEvent(event)

    def setup_pastebin_elements(self, layout: QVBoxLayout) -> None:
        """Set up the Pastebin fetch UI elements."""
        pastebin_layout = QHBoxLayout()

        self.pastebin_label = QLabel("PASTEBIN LOG FETCH", self)
        self.pastebin_label.setToolTip("Fetch a log file from Pastebin. Can be used more than once.")
        pastebin_layout.addWidget(self.pastebin_label)

        pastebin_layout.addSpacing(50)

        self.pastebin_id_input = QLineEdit(self)
        self.pastebin_id_input.setPlaceholderText("Enter Pastebin URL or ID")
        self.pastebin_id_input.setToolTip("Enter the Pastebin URL or ID to fetch the log. Can be used more than once.")
        pastebin_layout.addWidget(self.pastebin_id_input)

        self.pastebin_fetch_button = QPushButton("Fetch Log", self)
        self.pastebin_fetch_button.clicked.connect(self.fetch_pastebin_log)
        self.pastebin_fetch_button.clicked.connect(self.pastebin_id_input.clear)
        self.pastebin_fetch_button.setToolTip("Fetch the log file from Pastebin. Can be used more than once.")
        pastebin_layout.addWidget(self.pastebin_fetch_button)

        # Add the layout to the main layout (add it to an appropriate tab or section)
        layout.addLayout(pastebin_layout)

    def fetch_pastebin_log(self) -> None:
        input_text = self.pastebin_id_input.text().strip()
        url = input_text if self.pastebin_url_regex.match(input_text) else f"https://pastebin.com/{input_text}"

        # Create thread and worker
        pastebin_thread = QThread()
        pastebin_worker = PastebinFetchWorker(url)
        pastebin_worker.moveToThread(pastebin_thread)

        # Connect signals
        pastebin_thread.started.connect(pastebin_worker.run)
        pastebin_worker.finished.connect(pastebin_thread.quit)
        pastebin_worker.success.connect(lambda pb_source: QMessageBox.information(self, "Success", f"Log fetched from: {pb_source}"))
        pastebin_worker.error.connect(lambda err: QMessageBox.warning(self, "Error", f"Failed to fetch log: {err}", QMessageBox.StandardButton.NoButton, QMessageBox.StandardButton.NoButton))

        # Start thread
        pastebin_thread.start()

    def show_manual_docs_path_dialog(self) -> None:
        dialog = ManualPathDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            manual_path = dialog.get_path()
            CMain.get_manual_docs_path_gui(manual_path)

    def show_game_path_dialog(self) -> None:
        if CMain.game_path_gui is None:
            raise TypeError("CMain not initialized")

        dialog = GamePathDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            manual_path = dialog.get_path()
            CMain.game_path_gui.get_game_path_gui(manual_path)

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
            is_up_to_date = await CMain.is_latest_version(quiet=True)
            self.show_update_result(is_up_to_date)
        except CMain.UpdateCheckError as e:
            self.show_update_error(str(e))
        finally:
            self.is_update_check_running = False
            self.update_check_timer.stop()  # Ensure the timer is always stopped

    async def async_update_check_explicit(self) -> None:
        try:
            is_up_to_date = await CMain.is_latest_version(
                quiet=True, gui_request=True
            )
            self.show_update_result(is_up_to_date)
        except CMain.UpdateCheckError as e:
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
            update_popup_text = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Interface.update_popup_text") or ""
            result = QMessageBox.question(
                self,
                "CLASSIC UPDATE",
                update_popup_text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.NoButton
            )
            if result == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(
                    QUrl(
                        "https://github.com/evildarkarchon/CLASSIC-Fallout4/releases/latest"
                    )
                )

    def show_update_error(self, error_message: str) -> None:
        QMessageBox.warning(
            self, "Update Check Failed", f"Failed to check for updates: {error_message}", QMessageBox.StandardButton.NoButton, QMessageBox.StandardButton.NoButton
        )

    def setup_main_tab(self) -> None:
        layout = QVBoxLayout(self.main_tab)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        # Top section
        self.mods_folder_edit = self.setup_folder_section(
            layout, "STAGING MODS FOLDER", "Box_SelectedMods", self.select_folder_mods
        )
        self.mods_folder_edit.setToolTip("Select the folder where you stage your mods.")
        self.mods_folder_edit.setPlaceholderText("Optional: Select the folder where you stage your mods.")

        self.scan_folder_edit = self.setup_folder_section(
            layout, "CUSTOM SCAN FOLDER", "Box_SelectedScan", self.select_folder_scan
        )
        self.scan_folder_edit.setToolTip("Select a custom folder to scan for log files.")
        self.scan_folder_edit.setPlaceholderText("Optional: Select a custom folder to scan for log files.")



        self.setup_pastebin_elements(layout)

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
                QMessageBox.StandardButton.NoButton,
                QMessageBox.StandardButton.NoButton,
            )

    def help_popup_backup(self) -> None:
        help_popup_text = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Interface.help_popup_backup") or ""
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
            text = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)

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

        except Exception as e:  # noqa: BLE001
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
            ("AUDIO NOTIFICATIONS", "Audio Notifications")
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

        update_source_layout = QHBoxLayout()

        update_source_label = QLabel("Update Source")
        update_source_combo = QComboBox()
        update_sources = ("Nexus", "GitHub", "Both")
        update_source_combo.addItems(update_sources)

        # Set the ComboBox to adjust size based on content
        update_source_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

        # Optionally, reduce the spacing between the label and ComboBox
        update_source_layout.setSpacing(10)  # Adjust the spacing between label and combo box

        # Set layout margins to 0 to bring the label and combo box closer
        update_source_layout.setContentsMargins(0, 0, 0, 0)

        # Set the layout alignment to align left
        update_source_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Set the size policy to prevent expanding
        update_source_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        update_source_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Calculate the width of the longest item and set the ComboBox width accordingly
        font_metrics = QFontMetrics(update_source_combo.font())
        combo_width = max(font_metrics.horizontalAdvance(item) for item in update_sources) + 30
        update_source_combo.setFixedWidth(combo_width)

        # Set the default value if stored in settings
        current_value = CMain.classic_settings(str, "Update Source")
        if current_value is not None:
            update_source_combo.setCurrentText(current_value)
        else:
            CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.Update Source", "Nexus")

        update_source_combo.setToolTip("Select the source to check for updates. Nexus = stable, GitHub = latest, Both = check both")

        update_source_combo.currentTextChanged.connect(
            lambda value: CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.Update Source", value)
        )

        update_source_layout.addWidget(update_source_label)
        update_source_layout.addWidget(update_source_combo)

        # Add the update source layout below the checkboxes
        layout.addLayout(update_source_layout)

        # Add a separator after the checkboxes
        layout.addWidget(self.create_separator())

    def create_checkbox(self, label_text: str, setting: str) -> QCheckBox:
        checkbox = QCheckBox(label_text)
        value = CMain.classic_settings(bool, setting)
        if value is not None:
            checkbox.setChecked(value)
        else:
            CMain.yaml_settings(bool, CMain.YAML.Settings, f"CLASSIC_Settings.{setting}", False)
            checkbox.setChecked(False)

        checkbox.stateChanged.connect(
            lambda state: CMain.yaml_settings(bool, CMain.YAML.Settings, f"CLASSIC_Settings.{setting}", bool(state))
        )
        if setting == "Audio Notifications":
            checkbox.stateChanged.connect(
                lambda state: self.audio_player.toggle_audio(state)
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
                image: pb_source(CLASSIC Data/graphics/unchecked.png);
            }
            QCheckBox::indicator:checked {
                image: pb_source(CLASSIC Data/graphics/checked.png);
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
                "pb_source": "https://www.nexusmods.com/fallout4/articles/3115",
            },
            {
                "text": "FALLOUT 4 SETUP TIPS",
                "pb_source": "https://www.nexusmods.com/fallout4/articles/4141",
            },
            {
                "text": "IMPORTANT PATCHES LIST",
                "pb_source": "https://www.nexusmods.com/fallout4/articles/3769",
            },
            {
                "text": "BUFFOUT 4 NEXUS PAGE",
                "pb_source": "https://www.nexusmods.com/fallout4/mods/47359",
            },
            {
                "text": "CLASSIC NEXUS PAGE",
                "pb_source": "https://www.nexusmods.com/fallout4/mods/56255",
            },
            {
                "text": "CLASSIC GITHUB",
                "pb_source": "https://github.com/GuidanceOfGrace/CLASSIC-Fallout4",
            },
            {
                "text": "DDS TEXTURE SCANNER",
                "pb_source": "https://www.nexusmods.com/fallout4/mods/71588",
            },
            {"text": "BETHINI PIE", "pb_source": "https://www.nexusmods.com/site/mods/631"},
            {
                "text": "WRYE BASH TOOL",
                "pb_source": "https://www.nexusmods.com/fallout4/mods/20032",
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
                lambda _, url=data["pb_source"]: QDesktopServices.openUrl(QUrl(url))
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
        self.papyrus_button.setEnabled(True)  # Enable the button since monitoring is now implemented
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
            """Start monitoring the Papyrus logs for new errors.
This feature is not fully implemented."""
        )
        self.papyrus_button.setCheckable(True)
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
        dialog = CustomAboutDialog(self)
        dialog.exec()

    def help_popup_main(self) -> None:
        help_popup_text = CMain.yaml_settings(str, CMain.YAML.Main, "CLASSIC_Interface.help_popup_main") or ""
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
            CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.SCAN Custom Path", folder)

    def select_folder_mods(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Staging Mods Folder")
        if folder:
            self.mods_folder_edit.setText(folder)
            CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.MODS Folder Path", folder)

    def initialize_folder_paths(self) -> None:
        scan_folder = CMain.classic_settings(str, "SCAN Custom Path")
        mods_folder = CMain.classic_settings(str, "MODS Folder Path")

        if scan_folder:
            self.scan_folder_edit.setText(scan_folder)
        if mods_folder:
            self.mods_folder_edit.setText(mods_folder)

    def select_folder_ini(self) -> None:
        folder = QFileDialog.getExistingDirectory(self)
        if folder:
            CMain.yaml_settings(str, CMain.YAML.Settings, "CLASSIC_Settings.INI Folder Path", folder)
            QMessageBox.information(self, "New INI Path Set", f"You have set the new path to: \n{folder}")

    @staticmethod
    def open_settings() -> None:
        settings_file = "CLASSIC Settings.yaml"
        QDesktopServices.openUrl(QUrl.fromLocalFile(settings_file))

    def crash_logs_scan(self) -> None:
        if self.crash_logs_thread is None:
            self.crash_logs_thread = QThread()
            self.crash_logs_worker = CrashLogsScanWorker()
            self.crash_logs_worker.moveToThread(self.crash_logs_thread)

            self.crash_logs_worker.notify_sound_signal.connect(self.audio_player.play_notify_signal.emit)
            self.crash_logs_worker.error_sound_signal.connect(self.audio_player.play_error_signal.emit)

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

            self.game_files_worker.notify_sound_signal.connect(self.audio_player.play_notify_signal.emit)
            self.game_files_worker.error_sound_signal.connect(self.audio_player.play_error_signal.emit)

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
        """Start or stop the Papyrus monitoring"""
        if self.papyrus_button.isChecked():
            self.start_papyrus_monitoring()
        else:
            self.stop_papyrus_monitoring()

    def start_papyrus_monitoring(self) -> None:
        """Start monitoring Papyrus logs"""
        if self.papyrus_monitor_thread is None:
            # Create new thread and worker
            self.papyrus_monitor_thread = QThread()
            self.papyrus_monitor_worker = PapyrusMonitorWorker()
            self.papyrus_monitor_worker.moveToThread(self.papyrus_monitor_thread)

            # Connect signals
            self.papyrus_monitor_thread.started.connect(self.papyrus_monitor_worker.run)
            self.papyrus_monitor_worker.statsUpdated.connect(self.update_papyrus_stats)
            self.papyrus_monitor_worker.error.connect(self.handle_papyrus_error)

            # Start monitoring
            self.papyrus_button.setText("STOP PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet(
                """
                QPushButton {
                    color: black;
                    background: rgb(237, 45, 45);  /* Red background */
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                    font-size: 14px;
                }
                """
            )
            self.papyrus_monitor_thread.start()

    def stop_papyrus_monitoring(self) -> None:
        """Stop monitoring Papyrus logs"""
        if self.papyrus_monitor_worker:
            self.papyrus_monitor_worker.stop()

        if self.papyrus_monitor_thread:
            self.papyrus_monitor_thread.quit()
            self.papyrus_monitor_thread.wait()

            # Reset thread and worker
            self.papyrus_monitor_thread = None
            self.papyrus_monitor_worker = None

            # Update UI
            self.papyrus_button.setText("START PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet(
                """
                QPushButton {
                    color: black;
                    background: rgb(45, 237, 138);  /* Green background */
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                    font-size: 14px;
                }
                """
            )
            self.papyrus_button.setChecked(False)
            self.output_text_box.append("\n=== Papyrus monitoring stopped ===\n")

    def update_papyrus_stats(self, stats: PapyrusStats) -> None:
        """Update the UI with new Papyrus statistics"""
        message = (
            f"\n=== Papyrus Log Stats [{stats.timestamp.strftime('%H:%M:%S')}] ===\n"
            f"Number of Dumps: {stats.dumps}\n"
            f"Number of Stacks: {stats.stacks}\n"
            f"Dumps/Stacks Ratio: {stats.ratio:.3f}\n"
            f"Number of Warnings: {stats.warnings}\n"
            f"Number of Errors: {stats.errors}\n"
        )
        self.output_text_box.append(message)

        # Scroll to the bottom after adding the new message
        self.output_text_box.verticalScrollBar().setValue(
            self.output_text_box.verticalScrollBar().maximum()
        )

        self._last_stats = stats

    def handle_papyrus_error(self, error_msg: str) -> None:
        """Handle errors from the Papyrus monitor"""
        self.output_text_box.append(f"\n❌ ERROR IN PAPYRUS MONITORING: {error_msg}\n")
        self.papyrus_button.setChecked(False)
        if self.papyrus_monitor_worker and not self.papyrus_monitor_worker.error_sound_played:
            self.audio_player.play_error_signal.emit()
            self.papyrus_monitor_worker.error_sound_played = True
        self.stop_papyrus_monitoring()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # noinspection PyBroadException
    try:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        app.exit(1)
    except Exception as _:  # noqa: BLE001
        error_text = traceback.format_exc()
        show_exception_box(error_text)
