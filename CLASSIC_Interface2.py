import os
import sys
import time
import platform
import subprocess
import multiprocessing
import asyncio
try:  # soundfile (specically its Numpy dependency) seem to cause virus alerts from some AV programs, including Windows Defender.
    import soundfile as sfile
    import sounddevice as sdev
    has_soundfile = True
except ImportError:
    has_soundfile = False
# sfile and sdev need Numpy
from PySide6.QtWidgets import (QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLineEdit, QLabel, QFileDialog, QSizePolicy, QMessageBox, QFrame,
                               QCheckBox, QGridLayout, QTextEdit)
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtCore import Qt, QUrl, QSize, QObject, Signal

import CLASSIC_Main as CMain
import CLASSIC_ScanGame as CGame
import CLASSIC_ScanLogs as CLogs

class OutputRedirector(QObject):
    outputWritten = Signal(str)

    def write(self, text):
        self.outputWritten.emit(str(text))

    def flush(self):
        pass

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Crash Log Auto Scanner & Setup Integrity Checker | {CMain.yaml_settings('CLASSIC Data/databases/CLASSIC Main.yaml', 'CLASSIC_Info.version')}")
        self.setWindowIcon(QIcon("CLASSIC Data/graphics/CLASSIC.ico"))
        self.setStyleSheet("font-family: Yu Gothic; font-size: 13px")
        self.setMinimumSize(700, 950)  # Increase minimum width from 650 to 700

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

        self.setup_main_tab()
        self.setup_output_redirection()
        self.output_buffer = ""
        CMain.main_generate_required()

    def setup_main_tab(self):
        layout = QVBoxLayout(self.main_tab)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(10)

        # Top section
        self.setup_folder_section(layout, "STAGING MODS FOLDER", "Box_SelectedMods", self.select_folder_mods)
        self.setup_folder_section(layout, "CUSTOM SCAN FOLDER", "Box_SelectedScan", self.select_folder_scan)

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

    def setup_output_text_box(self, layout):
        self.output_text_box = QTextEdit()
        self.output_text_box.setReadOnly(True)
        self.output_text_box.setStyleSheet("""
            QTextEdit {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 13px;
            }
        """)
        self.output_text_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.output_text_box.setMinimumHeight(150)  # Set a minimum height
        layout.addWidget(self.output_text_box)

    def process_lines(self, lines):
        for line in lines:
            stripped_line = line.rstrip()
            if stripped_line or line.endswith('\n'):
                self.output_text_box.append(stripped_line)

        # Scroll to the bottom of the text box
        scrollbar = self.output_text_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def setup_output_redirection(self):
        self.output_redirector = OutputRedirector()
        self.output_redirector.outputWritten.connect(self.update_output_text_box)
        sys.stdout = self.output_redirector
        sys.stderr = self.output_redirector  # Also redirect stderr


    def update_output_text_box(self, text):
        self.output_buffer += text
        lines = self.output_buffer.splitlines(True)  # Keep the newline characters

        if self.output_buffer.endswith('\n'):
            # Process all lines
            self.output_buffer = ""
            self.process_lines(lines)
        else:
            # Process all but the last line
            self.process_lines(lines[:-1])
            self.output_buffer = lines[-1]

    def create_separator(self):
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        return separator

    def setup_checkboxes(self, layout):
        checkbox_layout = QVBoxLayout()

        # Title for the checkbox section
        title_label = QLabel("CLASSIC SETTINGS")
        title_label.setAlignment(Qt.AlignCenter)
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
            ("MOVE INVALID LOGS", "Move Unsolved Logs")
        ]

        for index, (label, setting) in enumerate(checkboxes):
            checkbox = self.create_checkbox(label, setting)
            row = index // 3
            col = index % 3
            grid_layout.addWidget(checkbox, row, col, Qt.AlignLeft)

        checkbox_layout.addLayout(grid_layout)

        # Add some vertical spacing
        checkbox_layout.addSpacing(20)

        layout.addLayout(checkbox_layout)

        # Add a separator after the checkboxes
        layout.addWidget(self.create_separator())

    def create_checkbox(self, label_text, setting):
        checkbox = QCheckBox(label_text)
        checkbox.setChecked(CMain.classic_settings(setting))
        checkbox.stateChanged.connect(lambda state: CMain.yaml_settings("CLASSIC Settings.yaml", f"CLASSIC_Settings.{setting}", bool(state)))

        # Apply custom style sheet
        checkbox.setStyleSheet("""
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
        """)

        return checkbox

    def setup_folder_section(self, layout, title, box_name, browse_callback, tooltip=""):
        section_layout = QHBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(5)

        label = QLabel(title)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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

    def setup_main_buttons(self, layout):
        # Main action buttons
        main_buttons_layout = QHBoxLayout()
        main_buttons_layout.setSpacing(10)
        self.add_main_button(main_buttons_layout, "SCAN CRASH LOGS", self.crash_logs_scan)
        self.add_main_button(main_buttons_layout, "SCAN GAME FILES", self.game_files_scan)
        layout.addLayout(main_buttons_layout)

        # Bottom row buttons
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.setSpacing(5)
        self.add_bottom_button(bottom_buttons_layout, "CHANGE INI PATH", self.select_folder_ini)
        self.add_bottom_button(bottom_buttons_layout, "OPEN CLASSIC SETTINGS", self.open_settings)
        self.add_bottom_button(bottom_buttons_layout, "CHECK UPDATES", self.update_popup)
        layout.addLayout(bottom_buttons_layout)

    def setup_articles_section(self, layout):
        # Title for the articles section
        title_label = QLabel("ARTICLES / WEBSITES / NEXUS LINKS")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title_label)

        # Grid layout for article buttons
        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(10)
        grid_layout.setVerticalSpacing(10)

        button_data = [
            {"text": "BUFFOUT 4 INSTALLATION", "url": "https://www.nexusmods.com/fallout4/articles/3115"},
            {"text": "FALLOUT 4 SETUP TIPS", "url": "https://www.nexusmods.com/fallout4/articles/4141"},
            {"text": "IMPORTANT PATCHES LIST", "url": "https://www.nexusmods.com/fallout4/articles/3769"},
            {"text": "BUFFOUT 4 NEXUS PAGE", "url": "https://www.nexusmods.com/fallout4/mods/47359"},
            {"text": "CLASSIC NEXUS PAGE", "url": "https://www.nexusmods.com/fallout4/mods/56255"},
            {"text": "CLASSIC GITHUB", "url": "https://github.com/GuidanceOfGrace/CLASSIC-Fallout4"},
            {"text": "DDS TEXTURE SCANNER", "url": "https://www.nexusmods.com/fallout4/mods/71588"},
            {"text": "BETHINI TOOL", "url": "https://www.nexusmods.com/site/mods/631"},
            {"text": "WRYE BASH TOOL", "url": "https://www.nexusmods.com/fallout4/mods/20032"}
        ]

        for i, data in enumerate(button_data):
            button = QPushButton(data["text"])
            button.setFixedSize(180, 50)  # Set fixed size for buttons
            button.setStyleSheet("""
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
            """)
            button.clicked.connect(lambda _, url=data["url"]: QDesktopServices.openUrl(QUrl(url)))
            row = i // 3
            col = i % 3
            grid_layout.addWidget(button, row, col, Qt.AlignCenter)

        layout.addLayout(grid_layout)

        # Add some vertical spacing after the articles section
        layout.addSpacing(20)

    def setup_bottom_buttons(self, layout):
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(5)  # Reduce spacing between buttons

        # ABOUT button
        about_button = QPushButton("ABOUT")
        about_button.setFixedSize(80, 30)  # Reduce width
        about_button.clicked.connect(self.show_about)
        about_button.setStyleSheet("""
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """)
        bottom_layout.addWidget(about_button)

        # HELP button
        help_button = QPushButton("HELP")
        help_button.setFixedSize(80, 30)  # Reduce width
        help_button.clicked.connect(self.help_popup_main)
        help_button.setStyleSheet("""
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """)
        bottom_layout.addWidget(help_button)

        # PAPYRUS MONITORING button
        self.papyrus_button = QPushButton("START PAPYRUS MONITORING")
        self.papyrus_button.setFixedHeight(30)
        self.papyrus_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.papyrus_button.clicked.connect(self.toggle_papyrus_worker)
        self.papyrus_button.setStyleSheet("""
            QPushButton {
                color: black;
                background: rgb(45, 237, 138);
                border-radius: 10px;
                border: 1px solid black;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        bottom_layout.addWidget(self.papyrus_button)

        # EXIT button
        exit_button = QPushButton("EXIT")
        exit_button.setFixedSize(80, 30)  # Reduce width
        exit_button.clicked.connect(QApplication.quit)
        exit_button.setStyleSheet("""
            QPushButton {
                color: white;
                background: rgba(10, 10, 10, 0.75);
                border-radius: 10px;
                border: 1px solid white;
                font-size: 11px;
            }
        """)
        bottom_layout.addWidget(exit_button)

        layout.addLayout(bottom_layout)

    def show_about(self):
        about_text = ("Crash Log Auto Scanner & Setup Integrity Checker\n\n"
                    "Made by: Poet\n"
                    "Contributors: evildarkarchon | kittivelae | AtomicFallout757")
        QMessageBox.about(self, "About CLASSIC", about_text)

    def help_popup_main(self):
        help_popup_text = CMain.yaml_settings("CLASSIC Data/databases/CLASSIC Main.yaml", "CLASSIC_Interface.help_popup_main")
        QMessageBox.information(self, "NEED HELP?", help_popup_text)

    def toggle_papyrus_worker(self):
        # Implement Papyrus monitoring logic here
        if self.papyrus_button.text() == "START PAPYRUS MONITORING":
            self.papyrus_button.setText("STOP PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet("""
                QPushButton {
                    color: black;
                    background: rgb(240, 63, 40);
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                }
            """)
        else:
            self.papyrus_button.setText("START PAPYRUS MONITORING")
            self.papyrus_button.setStyleSheet("""
                QPushButton {
                    color: black;
                    background: rgb(45, 237, 138);
                    border-radius: 10px;
                    border: 1px solid black;
                    font-weight: bold;
                }
            """)

    def add_main_button(self, layout, text, callback, tooltip=""):
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setStyleSheet("""
            color: black;
            background: rgba(250, 250, 250, 0.90);
            border-radius: 10px;
            border: 1px solid white;
            font-size: 17px;
            font-weight: bold;  /* Add this line to make the text bold */
            min-height: 48px;
            max-height: 48px;
        """)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def add_bottom_button(self, layout, text, callback, tooltip=""):
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setStyleSheet("""
            color: white;
            background: rgba(10, 10, 10, 0.75);
            border-radius: 10px;
            border: 1px solid white;
            font-size: 11px;
            min-height: 32px;
            max-height: 32px;
        """)
        if tooltip:
            button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def select_folder_mods(self):
        folder = QFileDialog.getExistingDirectory(self)
        if folder:
            self.main_tab.findChild(QLineEdit, "Box_SelectedMods").setText(folder)
            CMain.yaml_settings("CLASSIC Settings.yaml", "CLASSIC_Settings.MODS Folder Path", folder)

    def select_folder_scan(self):
        folder = QFileDialog.getExistingDirectory(self)
        if folder:
            self.main_tab.findChild(QLineEdit, "Box_SelectedScan").setText(folder)
            CMain.yaml_settings("CLASSIC Settings.yaml", "CLASSIC_Settings.SCAN Custom Path", folder)

    def select_folder_ini(self):
        folder = QFileDialog.getExistingDirectory(self)
        if folder:
            CMain.yaml_settings("CLASSIC Settings.yaml", "CLASSIC_Settings.INI Folder Path", folder)
            QMessageBox.information(self, "New INI Path Set", f"You have set the new path to: \n{folder}")

    def open_settings(self):
        settings_file = "CLASSIC Settings.yaml"
        QDesktopServices.openUrl(QUrl.fromLocalFile(settings_file))

    def update_popup(self):
        # Implement update check logic here
        pass

    def crash_logs_scan(self):
        CLogs.crashlogs_scan()
        # Implement any UI updates or notifications here

    def game_files_scan(self):
        print(CGame.game_combined_result())
        print(CGame.mods_combined_result())
        CGame.write_combined_results()
        # Implement any UI updates or notifications here

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    outputredirector = OutputRedirector()
    window.show()
    sys.exit(app.exec())