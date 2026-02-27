"""
PySide6 desktop GUI for obsidian_to_anki.

Launch:
    python -m obsidian_to_anki --gui
    python -m obsidian_to_anki.gui
"""

import os
import subprocess
import sys
import traceback
from pathlib import Path

# Work around Wayland protocol errors on WSL2 (Qt6 defaults to Wayland
# via WSLg, which triggers buffer-size mismatches with the compositor).
if "microsoft" in os.uname().release.lower():
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

try:
    from PySide6.QtCore import QThread, Signal, QObject, Qt, QUrl, QTimer, QElapsedTimer
    from PySide6.QtGui import QDesktopServices, QFont, QTextCursor, QColor, QBrush
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QSizePolicy,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    print(
        "PySide6 is required for the GUI.\n"
        "Install it with:  pip install PySide6"
    )
    sys.exit(1)

from . import __version__
from .parser import parse_note
from .exporter import export
from . import config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPORT_STEP_NAMES = ["Parse note", "Copy images", "Generate Basic.txt", "Generate Cloze.txt"]
SYNC_STEP_NAMES = ["Parse", "Connect", "Analyze", "Sync", "Write IDs"]

STEP_ICONS = {
    "pending": "\u25CB",   # ○
    "running": "\u25CF",   # ●
    "done":    "\u2713",   # ✓
    "error":   "\u2717",   # ✗
    "skip":    "\u2014",   # —
}

STEP_COLORS = {
    "pending": "",
    "running": "color: #2196F3;",
    "done":    "color: #4CAF50;",
    "error":   "color: #F44336;",
    "skip":    "color: gray;",
}

STEP_BG_COLORS = {
    "pending": "",
    "running": "background-color: #E3F2FD; border-radius: 4px;",
    "done":    "background-color: #E8F5E9; border-radius: 4px;",
    "error":   "background-color: #FFEBEE; border-radius: 4px;",
    "skip":    "",
}

ROW_COLOR_SUCCESS = QColor("#E8F5E9")
ROW_COLOR_ERROR   = QColor("#FFEBEE")
ROW_COLOR_NEUTRAL = QColor("#F5F5F5")


# ---------------------------------------------------------------------------
# stdout capture → Qt signal
# ---------------------------------------------------------------------------

class StdoutRedirector(QObject):
    """Captures writes to sys.stdout and emits them as a Qt signal."""

    text_written = Signal(str)

    def __init__(self):
        super().__init__()

    def write(self, text: str):
        if text:
            self.text_written.emit(text)

    def flush(self):
        pass


# ---------------------------------------------------------------------------
# Export worker thread
# ---------------------------------------------------------------------------

class ConvertWorker(QThread):
    """Runs per-step export pipeline off the main thread."""

    file_started = Signal(str, int, int)       # filename, index, total
    step_update  = Signal(str, str, str)       # step_name, status, detail
    file_done    = Signal(str, int, int, bool, str) # filename, basic, cloze, ok, output_dir
    finished_ok  = Signal()
    finished_err = Signal(str)

    def __init__(self, path: str, anki_media: str, dry_run: bool, recursive: bool):
        super().__init__()
        self.path = path
        self.anki_media = anki_media
        self.dry_run = dry_run
        self.recursive = recursive

    # -- per-file pipeline ---------------------------------------------------

    def _run_single(self, file_path: Path, index: int, total: int):
        filename = file_path.name
        self.file_started.emit(filename, index, total)

        # Step 1 — Parse note
        self.step_update.emit("Parse note", "running", "")
        try:
            note = parse_note(file_path)
            bc = len(note.basic_cards)
            cc = len(note.cloze_cards)
            self.step_update.emit("Parse note", "done", f"{bc} basic, {cc} cloze")
        except Exception as e:
            self.step_update.emit("Parse note", "error", str(e))
            self.file_done.emit(filename, 0, 0, False, "")
            return

        # Steps 2–4 — delegated to export()
        export(note, self.anki_media, dry_run=self.dry_run, on_step=self.step_update.emit)
        self.file_done.emit(filename, bc, cc, True, str(note.file_path.parent))

    # -- batch ---------------------------------------------------------------

    def _run_batch(self, folder: Path):
        md_files = config.discover_md_files(folder, self.recursive)

        if not md_files:
            print(f"[batch] No .md files found in: {folder}")
            return

        print(f"[batch] Found {len(md_files)} file(s) to process\n")

        for i, md_file in enumerate(md_files, 1):
            try:
                self._run_single(md_file, i, len(md_files))
            except Exception as e:
                print(f"[error] {md_file.name}: {e}\n{traceback.format_exc()}")
                self.file_done.emit(md_file.name, 0, 0, False, "")

    # -- entry point ---------------------------------------------------------

    def run(self):
        try:
            target = Path(self.path).resolve()
            if target.is_dir():
                self._run_batch(target)
            elif target.is_file():
                self._run_single(target, 1, 1)
            else:
                self.finished_err.emit(f"'{self.path}' is not a valid file or folder.")
                return
            self.finished_ok.emit()
        except Exception as e:
            print(f"[error] {traceback.format_exc()}")
            self.finished_err.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Sync worker thread
# ---------------------------------------------------------------------------

class SyncWorker(QThread):
    """Runs sync pipeline off the main thread."""

    file_started = Signal(str, int, int)       # filename, index, total
    step_update  = Signal(str, str, str)       # step_name, status, detail
    file_done    = Signal(str, int, int, int, int, bool)  # filename, new, updated, unchanged, deleted, ok
    backup_done  = Signal(str)                 # wsl_backup_dir path
    finished_ok  = Signal()
    finished_err = Signal(str)

    def __init__(self, path: str, url: str, dry_run: bool, recursive: bool, delete_orphans: bool, backup: bool):
        super().__init__()
        self.path = path
        self.url = url
        self.dry_run = dry_run
        self.recursive = recursive
        self.delete_orphans = delete_orphans
        self.backup = backup

    def _run_single(self, file_path: Path, index: int, total: int):
        from .ankiconnect import AnkiConnectClient
        from .sync import sync_note

        filename = file_path.name
        self.file_started.emit(filename, index, total)

        try:
            note = parse_note(file_path)
        except Exception as e:
            print(f"[error] Parse failed for {filename}:\n{traceback.format_exc()}")
            self.step_update.emit("Parse", "error", str(e))
            self.file_done.emit(filename, 0, 0, 0, 0, False)
            return

        client = AnkiConnectClient(self.url)
        try:
            result = sync_note(
                note, client,
                dry_run=self.dry_run,
                delete_orphans=self.delete_orphans,
                on_step=self.step_update.emit,
            )
        except Exception as e:
            print(f"[error] Sync failed for {filename}:\n{traceback.format_exc()}")
            self.step_update.emit("Sync", "error", str(e))
            self.file_done.emit(filename, 0, 0, 0, 0, False)
            return

        ok = result.error_count == 0
        self.file_done.emit(
            filename,
            result.new_count,
            result.updated_count,
            result.unchanged_count,
            result.deleted_from_obsidian,
            ok,
        )

    def _run_batch(self, folder: Path):
        md_files = config.discover_md_files(folder, self.recursive)

        if not md_files:
            print(f"[batch] No .md files found in: {folder}")
            return

        print(f"[batch] Found {len(md_files)} file(s) to sync\n")

        for i, md_file in enumerate(md_files, 1):
            try:
                self._run_single(md_file, i, len(md_files))
            except Exception as e:
                print(f"[error] {md_file.name}:\n{traceback.format_exc()}")
                self.file_done.emit(md_file.name, 0, 0, 0, 0, False)

    def run(self):
        from .ankiconnect import AnkiConnectClient, AnkiConnectError
        from datetime import datetime
        from pathlib import PureWindowsPath

        try:
            # Pre-check connection
            client = AnkiConnectClient(self.url)
            if not client.ping():
                self.finished_err.emit(
                    f"Cannot reach AnkiConnect at {self.url}. "
                    "Is Anki running with AnkiConnect installed?"
                )
                return

            # Backup collection before sync
            if self.backup and not self.dry_run:
                try:
                    media_dir = client.get_media_dir_path()
                    if not media_dir:
                        self.finished_err.emit("Backup failed: could not determine Anki media path.")
                        return
                    # media_dir is a Windows path; use PureWindowsPath to parse it
                    win_profile_dir = PureWindowsPath(media_dir).parent
                    win_backup_dir = win_profile_dir / "backups"

                    # Convert to WSL path so we can mkdir from Linux
                    wsl_backup_dir = subprocess.check_output(
                        ["wslpath", "-u", str(win_backup_dir)], text=True,
                    ).strip()
                    Path(wsl_backup_dir).mkdir(exist_ok=True)

                    all_decks = client.deck_names()
                    root_decks = [d for d in all_decks if "::" not in d]
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                    print(f"[backup] Backing up {len(root_decks)} root deck(s)...")
                    for deck in root_decks:
                        safe_name = deck.replace("/", "_").replace("\\", "_")
                        win_apkg_path = str(win_backup_dir / f"{safe_name}_{timestamp}.apkg")
                        print(f"[backup] Exporting '{deck}' → {win_apkg_path}")
                        client.export_package(deck, win_apkg_path)
                        print(f"[backup] Done: {win_apkg_path}")
                    print(f"[backup] All backups complete.\n")
                    self.backup_done.emit(wsl_backup_dir)
                except AnkiConnectError as e:
                    self.finished_err.emit(f"Backup failed: {e}")
                    return

            target = Path(self.path).resolve()
            if target.is_dir():
                self._run_batch(target)
            elif target.is_file():
                self._run_single(target, 1, 1)
            else:
                self.finished_err.emit(f"'{self.path}' is not a valid file or folder.")
                return
            self.finished_ok.emit()
        except AnkiConnectError as e:
            print(f"[error] {traceback.format_exc()}")
            self.finished_err.emit(str(e))
        except Exception as e:
            print(f"[error] {traceback.format_exc()}")
            self.finished_err.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Obsidian \u2192 Anki v{__version__}")
        self.resize(900, 700)

        self._worker: ConvertWorker | SyncWorker | None = None
        self._redirector = StdoutRedirector()
        self._redirector.text_written.connect(self._append_details)
        self._is_batch = False
        self._total_files = 0
        self._files_done = 0
        self._current_file = ""
        self._viewing_file = ""
        self._file_steps: dict[str, dict[str, tuple[str, str]]] = {}
        self._single_output_dir = ""
        self._current_step_names: list[str] = EXPORT_STEP_NAMES
        self._step_timers: dict[str, QElapsedTimer] = {}

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ==================== INPUT ZONE ====================
        input_zone = QWidget()
        input_zone.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        input_lay = QVBoxLayout(input_zone)
        input_lay.setContentsMargins(0, 0, 0, 0)

        # -- Input path -----------------------------------------------------
        grp_input = QGroupBox("Input Path")
        h = QHBoxLayout(grp_input)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select a .md file or folder\u2026")
        btn_file = QPushButton("Browse File")
        btn_dir = QPushButton("Browse Dir")
        btn_file.clicked.connect(self._browse_file)
        btn_dir.clicked.connect(self._browse_dir)
        h.addWidget(self.input_edit, 1)
        h.addWidget(btn_file)
        h.addWidget(btn_dir)
        input_lay.addWidget(grp_input)

        # -- Mode toggle ----------------------------------------------------
        grp_mode = QGroupBox("Mode")
        mode_lay = QHBoxLayout(grp_mode)
        self.radio_export = QRadioButton("Export TSV")
        self.radio_sync = QRadioButton("Sync to Anki")
        self.radio_export.setChecked(True)
        self.radio_export.toggled.connect(self._on_mode_changed)
        mode_lay.addWidget(self.radio_export)
        mode_lay.addWidget(self.radio_sync)
        mode_lay.addStretch()

        # Connection status indicator
        self.conn_status = QLabel("")
        self.conn_status.setStyleSheet("font-size: 12px;")
        mode_lay.addWidget(self.conn_status)
        input_lay.addWidget(grp_mode)

        # -- Anki media path (export mode) ----------------------------------
        self.grp_media = QGroupBox("Anki Media Path")
        h2 = QHBoxLayout(self.grp_media)
        self.media_edit = QLineEdit()
        self.media_edit.setPlaceholderText("Path to Anki's collection.media folder")
        btn_media = QPushButton("Browse\u2026")
        btn_media.clicked.connect(self._browse_media)
        h2.addWidget(self.media_edit, 1)
        h2.addWidget(btn_media)
        input_lay.addWidget(self.grp_media)

        # Pre-fill from config
        cfg = config.load()
        if "anki_media_path" in cfg:
            self.media_edit.setText(cfg["anki_media_path"])

        # -- AnkiConnect URL (sync mode) ------------------------------------
        self.grp_url = QGroupBox("AnkiConnect URL")
        h_url = QHBoxLayout(self.grp_url)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://127.0.0.1:8765")
        self.url_edit.setText(cfg.get("ankiconnect_url", config.DEFAULT_ANKICONNECT_URL))
        h_url.addWidget(self.url_edit, 1)
        input_lay.addWidget(self.grp_url)
        self.grp_url.hide()

        # -- Options --------------------------------------------------------
        h3 = QHBoxLayout()
        self.chk_dry = QCheckBox("Dry run")
        self.chk_recursive = QCheckBox("Recursive")
        self.chk_delete_orphans = QCheckBox("Delete orphans")
        self.chk_backup = QCheckBox("Backup collection")
        self.chk_backup.setChecked(True)
        h3.addWidget(self.chk_dry)
        h3.addWidget(self.chk_recursive)
        h3.addWidget(self.chk_delete_orphans)
        h3.addWidget(self.chk_backup)
        h3.addStretch()
        input_lay.addLayout(h3)
        self.chk_delete_orphans.hide()
        self.chk_backup.hide()

        # -- Action button --------------------------------------------------
        self.btn_action = QPushButton("Convert")
        self.btn_action.setFixedHeight(36)
        self.btn_action.clicked.connect(self._start_action)
        input_lay.addWidget(self.btn_action)

        main_layout.addWidget(input_zone)

        # ==================== SEPARATOR ====================
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)

        # ==================== OUTPUT ZONE ====================
        output_zone = QWidget()
        output_lay = QVBoxLayout(output_zone)
        output_lay.setContentsMargins(0, 4, 0, 0)

        # -- Batch progress bar ---------------------------------------------
        self.batch_progress = QProgressBar()
        self.batch_progress.setFormat("Processing %v of %m files...")
        self.batch_progress.setStyleSheet(
            "QProgressBar {"
            "  border: 1px solid #ccc;"
            "  border-radius: 4px;"
            "  text-align: center;"
            "  height: 22px;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: #4CAF50;"
            "  border-radius: 3px;"
            "}"
        )
        output_lay.addWidget(self.batch_progress)
        self.batch_progress.hide()

        # -- Progress section (enhanced step rows) --------------------------
        self.progress_section = QWidget()
        self.progress_section.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        prog_lay = QVBoxLayout(self.progress_section)
        prog_lay.setContentsMargins(0, 4, 0, 0)
        prog_lay.setSpacing(1)

        self.progress_header = QLabel()
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        prog_lay.addWidget(self.progress_header)

        # Create step rows for both modes (icon, name, detail, time, frame)
        self.step_rows: dict[str, tuple[QLabel, QLabel, QLabel, QLabel, QFrame]] = {}
        all_step_names = list(EXPORT_STEP_NAMES) + [
            s for s in SYNC_STEP_NAMES if s not in EXPORT_STEP_NAMES
        ]
        for name in all_step_names:
            frame = QFrame()
            frame.setStyleSheet("padding: 1px 4px; border-radius: 4px;")
            row_lay = QHBoxLayout(frame)
            row_lay.setContentsMargins(4, 1, 4, 1)

            icon_lbl = QLabel(STEP_ICONS["pending"])
            icon_font = icon_lbl.font()
            icon_font.setPointSize(14)
            icon_lbl.setFont(icon_font)
            icon_lbl.setFixedWidth(24)

            name_lbl = QLabel(name)

            detail_lbl = QLabel("")
            detail_lbl.setStyleSheet("color: gray;")

            time_lbl = QLabel("")
            time_lbl.setStyleSheet("color: #888; font-size: 11px;")
            time_lbl.setFixedWidth(60)
            time_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            row_lay.addWidget(icon_lbl)
            row_lay.addWidget(name_lbl)
            row_lay.addWidget(detail_lbl, 1)
            row_lay.addWidget(time_lbl)

            prog_lay.addWidget(frame)
            self.step_rows[name] = (icon_lbl, name_lbl, detail_lbl, time_lbl, frame)

        output_lay.addWidget(self.progress_section)
        self.progress_section.hide()

        # -- Open folder buttons -----------------------------------------------
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.clicked.connect(self._open_single_folder)
        output_lay.addWidget(self.open_folder_btn)
        self.open_folder_btn.hide()

        # -- Details / backup button row ---------------------------------------
        btn_row = QHBoxLayout()
        self.details_btn = QPushButton("Show Log")
        self.details_btn.setFixedWidth(80)
        self.details_btn.clicked.connect(self._toggle_details)
        btn_row.addWidget(self.details_btn)
        self.details_btn.hide()

        self.open_backup_btn = QPushButton("Open Backup Folder")
        self.open_backup_btn.setFixedWidth(140)
        self.open_backup_btn.clicked.connect(self._open_backup_folder)
        btn_row.addWidget(self.open_backup_btn)
        self.open_backup_btn.hide()
        self._backup_dir = ""

        btn_row.addStretch()
        output_lay.addLayout(btn_row)

        # -- Results section (direct in output layout) ----------------------
        self.results_section = QWidget()
        res_lay = QVBoxLayout(self.results_section)
        res_lay.setContentsMargins(0, 8, 0, 0)

        self.results_header = QLabel("Results")
        self.results_header.setStyleSheet("font-weight: bold;")
        res_lay.addWidget(self.results_header)

        self.results_table = QTableWidget(0, 5)
        self._update_results_columns_for_mode()
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setStyleSheet(
            "QTableWidget {"
            "  alternate-background-color: #FAFAFA;"
            "  gridline-color: #E0E0E0;"
            "}"
            "QHeaderView::section {"
            "  background-color: #F5F5F5;"
            "  font-weight: bold;"
            "  padding: 4px;"
            "  border: 1px solid #E0E0E0;"
            "}"
        )
        self.results_table.setMinimumHeight(150)
        self.results_table.cellClicked.connect(self._on_result_clicked)
        res_lay.addWidget(self.results_table)

        output_lay.addWidget(self.results_section, 1)
        self.results_section.hide()

        # -- Details log dialog (separate window) ---------------------------
        self._details_dialog = QDialog(self)
        self._details_dialog.setWindowTitle("Log Output")
        self._details_dialog.resize(700, 400)
        dlg_lay = QVBoxLayout(self._details_dialog)

        self.details_area = QTextEdit()
        self.details_area.setReadOnly(True)
        self.details_area.setFont(QFont("Consolas", 9))
        dlg_lay.addWidget(self.details_area)

        dlg_btn_row = QHBoxLayout()
        dlg_btn_row.addStretch()
        self.copy_details_btn = QPushButton("Copy All")
        self.copy_details_btn.setFixedWidth(80)
        self.copy_details_btn.clicked.connect(self._copy_details)
        dlg_btn_row.addWidget(self.copy_details_btn)
        dlg_lay.addLayout(dlg_btn_row)

        main_layout.addWidget(output_zone, 1)

        # Initial mode setup
        self._on_mode_changed()

    # -- mode switching -----------------------------------------------------

    def _on_mode_changed(self):
        is_sync = self.radio_sync.isChecked()
        self.grp_media.setVisible(not is_sync)
        self.grp_url.setVisible(is_sync)
        self.chk_delete_orphans.setVisible(is_sync)
        self.chk_backup.setVisible(is_sync)
        self.btn_action.setText("Sync" if is_sync else "Convert")

        # Update step visibility
        self._current_step_names = SYNC_STEP_NAMES if is_sync else EXPORT_STEP_NAMES
        for name in self.step_rows:
            _icon_lbl, _name_lbl, _detail_lbl, _time_lbl, frame = self.step_rows[name]
            visible = name in self._current_step_names
            frame.setVisible(visible)

        # Check connection when switching to sync mode
        if is_sync:
            self._check_connection()
        else:
            self.conn_status.setText("")

    def _check_connection(self):
        """Check AnkiConnect connectivity in background."""
        self.conn_status.setText("Checking...")
        self.conn_status.setStyleSheet("font-size: 12px; color: gray;")
        QTimer.singleShot(100, self._do_check_connection)

    def _do_check_connection(self):
        from .ankiconnect import AnkiConnectClient
        url = self.url_edit.text().strip() or config.DEFAULT_ANKICONNECT_URL
        client = AnkiConnectClient(url, timeout=3)
        if client.ping():
            self.conn_status.setText("\u2713 Connected")
            self.conn_status.setStyleSheet("font-size: 12px; color: #4CAF50;")
        else:
            self.conn_status.setText("\u2717 Not connected")
            self.conn_status.setStyleSheet("font-size: 12px; color: #F44336;")

    def _update_results_columns_for_mode(self):
        is_sync = self.radio_sync.isChecked()
        if is_sync:
            self.results_table.setColumnCount(6)
            self.results_table.setHorizontalHeaderLabels(
                ["File", "New", "Updated", "Unchanged", "Deleted", "Status"]
            )
        else:
            self.results_table.setColumnCount(5)
            self.results_table.setHorizontalHeaderLabels(
                ["File", "Basic", "Cloze", "Status", ""]
            )
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, self.results_table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    # -- browse helpers -----------------------------------------------------

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select markdown file", "", "Markdown (*.md);;All Files (*)"
        )
        if path:
            self.input_edit.setText(path)

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            self.input_edit.setText(path)

    def _browse_media(self):
        path = QFileDialog.getExistingDirectory(self, "Select Anki collection.media folder")
        if path:
            self.media_edit.setText(path)

    # -- start action -------------------------------------------------------

    def _start_action(self):
        if self.radio_sync.isChecked():
            self._start_sync()
        else:
            self._start_convert()

    def _start_convert(self):
        input_path = self.input_edit.text().strip()
        media_path = self.media_edit.text().strip()

        if not input_path:
            self._show_validation_error("Please select an input file or folder.")
            return
        if not media_path:
            self._show_validation_error("Please set the Anki media path.")
            return

        # Save media path to config for future runs
        cfg = config.load()
        if cfg.get("anki_media_path") != media_path:
            cfg["anki_media_path"] = media_path
            config.save(cfg)

        self._reset_ui_state()
        self._current_step_names = EXPORT_STEP_NAMES

        # Redirect stdout for the duration of the worker
        self._old_stdout = sys.stdout
        sys.stdout = self._redirector

        self._worker = ConvertWorker(
            input_path, media_path,
            dry_run=self.chk_dry.isChecked(),
            recursive=self.chk_recursive.isChecked(),
        )
        self._worker.file_started.connect(self._on_file_started)
        self._worker.step_update.connect(self._on_step_update)
        self._worker.file_done.connect(self._on_export_file_done)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _start_sync(self):
        input_path = self.input_edit.text().strip()
        url = self.url_edit.text().strip() or config.DEFAULT_ANKICONNECT_URL

        if not input_path:
            self._show_validation_error("Please select an input file or folder.")
            return

        # Save URL to config
        cfg = config.load()
        if cfg.get("ankiconnect_url") != url:
            cfg["ankiconnect_url"] = url
            config.save(cfg)

        self._reset_ui_state()
        self._current_step_names = SYNC_STEP_NAMES
        self._update_results_columns_for_mode()

        # Redirect stdout
        self._old_stdout = sys.stdout
        sys.stdout = self._redirector

        self._worker = SyncWorker(
            input_path, url,
            dry_run=self.chk_dry.isChecked(),
            recursive=self.chk_recursive.isChecked(),
            delete_orphans=self.chk_delete_orphans.isChecked(),
            backup=self.chk_backup.isChecked(),
        )
        self._worker.file_started.connect(self._on_file_started)
        self._worker.step_update.connect(self._on_step_update)
        self._worker.file_done.connect(self._on_sync_file_done)
        self._worker.backup_done.connect(self._on_backup_done)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _reset_ui_state(self):
        self._is_batch = False
        self._total_files = 0
        self._files_done = 0
        self._current_file = ""
        self._viewing_file = ""
        self._file_steps.clear()
        self._single_output_dir = ""
        self.open_folder_btn.hide()
        self.open_backup_btn.hide()
        self._backup_dir = ""
        self.details_area.clear()
        self.results_table.setRowCount(0)
        self.results_section.hide()
        self._details_dialog.hide()
        self._reset_steps()
        self.progress_section.hide()
        self.batch_progress.hide()
        self.batch_progress.setValue(0)
        self.details_btn.show()
        self.btn_action.setEnabled(False)

    def _show_validation_error(self, msg: str):
        self.progress_section.show()
        self.progress_header.setText(f"\u2717 {msg}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #F44336;")
        self._reset_steps()

    def _reset_steps(self):
        for name in self._current_step_names:
            if name in self.step_rows:
                icon_lbl, _name_lbl, detail_lbl, time_lbl, frame = self.step_rows[name]
                icon_lbl.setText(STEP_ICONS["pending"])
                icon_lbl.setStyleSheet("")
                detail_lbl.setText("")
                time_lbl.setText("")
                frame.setStyleSheet("padding: 1px 4px; border-radius: 4px;")
        self._step_timers.clear()

    def _restore_stdout(self):
        sys.stdout = self._old_stdout

    # -- signal handlers (shared) -------------------------------------------

    def _on_file_started(self, filename: str, index: int, total: int):
        self._total_files = total
        self._is_batch = total > 1
        self._current_file = filename
        self._viewing_file = filename
        self._file_steps[filename] = {name: ("pending", "") for name in self._current_step_names}

        self.progress_section.show()
        if self._is_batch:
            self.progress_header.setText(f"Processing: {filename}    ({index}/{total})")
            # Show and update batch progress bar
            self.batch_progress.setMaximum(total)
            self.batch_progress.setValue(index - 1)
            self.batch_progress.show()
        else:
            self.progress_header.setText(f"Processing: {filename}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")

        self._reset_steps()

        # Update step visibility for current mode
        for name in self.step_rows:
            _icon_lbl, _name_lbl, _detail_lbl, _time_lbl, frame = self.step_rows[name]
            visible = name in self._current_step_names
            frame.setVisible(visible)

        # Show real output filenames in step labels (export mode)
        if not self.radio_sync.isChecked():
            stem = Path(filename).stem
            if "Generate Basic.txt" in self.step_rows:
                self.step_rows["Generate Basic.txt"][1].setText(f"Generate {stem} - Basic.txt")
            if "Generate Cloze.txt" in self.step_rows:
                self.step_rows["Generate Cloze.txt"][1].setText(f"Generate {stem} - Cloze.txt")

        if self._is_batch:
            self.results_section.show()

    def _set_step_display(self, step_name: str, status: str, detail: str):
        """Update the icon, colour, background, and detail label for a single step row."""
        if step_name not in self.step_rows:
            return
        icon_lbl, _name_lbl, detail_lbl, time_lbl, frame = self.step_rows[step_name]
        icon_lbl.setText(STEP_ICONS.get(status, STEP_ICONS["pending"]))
        icon_lbl.setStyleSheet(STEP_COLORS.get(status, ""))
        detail_lbl.setText(detail)

        # Background color
        bg = STEP_BG_COLORS.get(status, "")
        frame.setStyleSheet(f"padding: 1px 4px; {bg}")

        # Timer management
        if status == "running":
            timer = QElapsedTimer()
            timer.start()
            self._step_timers[step_name] = timer
            time_lbl.setText("")
        elif status in ("done", "error"):
            timer = self._step_timers.pop(step_name, None)
            if timer:
                elapsed_ms = timer.elapsed()
                if elapsed_ms >= 1000:
                    time_lbl.setText(f"{elapsed_ms / 1000:.1f}s")
                else:
                    time_lbl.setText(f"{elapsed_ms}ms")
            else:
                time_lbl.setText("")
        else:
            time_lbl.setText("")

    def _on_step_update(self, step_name: str, status: str, detail: str):
        if step_name not in self.step_rows:
            return

        # Always store
        if self._current_file in self._file_steps:
            self._file_steps[self._current_file][step_name] = (status, detail)

        # Only update UI if viewing the file being processed
        if self._viewing_file == self._current_file:
            self._set_step_display(step_name, status, detail)

    # -- export file done ---------------------------------------------------

    def _on_export_file_done(self, filename: str, basic_count: int, cloze_count: int,
                              ok: bool, output_dir: str):
        self._files_done += 1

        if not self._is_batch:
            self._single_output_dir = output_dir
            return

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        self.results_table.setItem(row, 0, QTableWidgetItem(filename))
        self.results_table.setItem(row, 1, QTableWidgetItem(str(basic_count)))
        self.results_table.setItem(row, 2, QTableWidgetItem(str(cloze_count)))

        if not ok:
            status_text = "\u2717 Error"
            color = ROW_COLOR_ERROR
        elif basic_count == 0 and cloze_count == 0:
            status_text = "\u2014 No cards"
            color = ROW_COLOR_NEUTRAL
        else:
            status_text = "\u2713 Exported"
            color = ROW_COLOR_SUCCESS
        self.results_table.setItem(row, 3, QTableWidgetItem(status_text))

        if output_dir:
            btn = QPushButton("Open")
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda _checked, p=output_dir: self._open_folder(p))
            self.results_table.setCellWidget(row, 4, btn)

        self._color_result_row(row, color)

        # Update batch progress
        self.batch_progress.setValue(self._files_done)

        done = row + 1
        self.results_header.setText(f"Results    {done}/{self._total_files} files")

    # -- sync file done -----------------------------------------------------

    def _on_sync_file_done(self, filename: str, new_count: int, updated_count: int,
                            unchanged_count: int, deleted_count: int, ok: bool):
        self._files_done += 1

        if not self._is_batch:
            return

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        self.results_table.setItem(row, 0, QTableWidgetItem(filename))
        self.results_table.setItem(row, 1, QTableWidgetItem(str(new_count)))
        self.results_table.setItem(row, 2, QTableWidgetItem(str(updated_count)))
        self.results_table.setItem(row, 3, QTableWidgetItem(str(unchanged_count)))
        self.results_table.setItem(row, 4, QTableWidgetItem(str(deleted_count)))

        if not ok:
            status_text = "\u2717 Error"
            color = ROW_COLOR_ERROR
        elif new_count == 0 and updated_count == 0:
            status_text = "\u2713 Up to date"
            color = ROW_COLOR_NEUTRAL
        else:
            status_text = "\u2713 Synced"
            color = ROW_COLOR_SUCCESS
        self.results_table.setItem(row, 5, QTableWidgetItem(status_text))

        self._color_result_row(row, color)

        # Update batch progress
        self.batch_progress.setValue(self._files_done)

        done = row + 1
        self.results_header.setText(f"Results    {done}/{self._total_files} files")

    # -- finished handlers --------------------------------------------------

    def _on_done(self):
        self._restore_stdout()

        if not self.progress_section.isVisible():
            self.progress_section.show()
            self.progress_header.setText("No .md files found")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        elif self._is_batch:
            self._add_summary_row()
            # Count successes (skip TOTAL row)
            status_col = 5 if self.radio_sync.isChecked() else 3
            ok_count = 0
            for row in range(self.results_table.rowCount()):
                name_item = self.results_table.item(row, 0)
                if name_item and name_item.text() == "TOTAL":
                    continue
                status_item = self.results_table.item(row, status_col)
                if status_item and "\u2713" in status_item.text():
                    ok_count += 1
            total = self._total_files
            action = "synced" if self.radio_sync.isChecked() else "exported"
            self.progress_header.setText(f"\u2713 Done \u2014 {ok_count}/{total} files {action}")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #4CAF50;")
            # Finalize progress bar
            self.batch_progress.setValue(self.batch_progress.maximum())
            self.batch_progress.setFormat("Done \u2014 %v files processed")
        else:
            action = "Sync" if self.radio_sync.isChecked() else "Export"
            self.progress_header.setText(f"\u2713 {action} complete")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #4CAF50;")
            if not self.radio_sync.isChecked() and self._single_output_dir:
                self.open_folder_btn.show()

        self.btn_action.setEnabled(True)

    def _on_error(self, msg: str):
        self._restore_stdout()
        self.progress_section.show()
        self.progress_header.setText(f"\u2717 Error: {msg}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #F44336;")
        self.btn_action.setEnabled(True)
        # Auto-open log dialog so the user can see the full traceback
        if not self._details_dialog.isVisible():
            self._details_dialog.show()

    # -- results table interaction ------------------------------------------

    def _on_result_clicked(self, row: int, _col: int):
        item = self.results_table.item(row, 0)
        if not item:
            return
        filename = item.text()
        # Guard against TOTAL row
        if filename == "TOTAL":
            return
        self._viewing_file = filename
        self._load_file_steps(filename)

    def _load_file_steps(self, filename: str):
        steps = self._file_steps.get(filename, {})
        for name in self._current_step_names:
            status, detail = steps.get(name, ("pending", ""))
            self._set_step_display(name, status, detail)
        if not self.radio_sync.isChecked():
            stem = Path(filename).stem
            if "Generate Basic.txt" in self.step_rows:
                self.step_rows["Generate Basic.txt"][1].setText(f"Generate {stem} - Basic.txt")
            if "Generate Cloze.txt" in self.step_rows:
                self.step_rows["Generate Cloze.txt"][1].setText(f"Generate {stem} - Cloze.txt")
        self.progress_header.setText(f"Steps: {filename}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")

    # -- color helpers ------------------------------------------------------

    def _color_result_row(self, row: int, color: QColor):
        """Set the background color for all cells in a results table row."""
        brush = QBrush(color)
        for col in range(self.results_table.columnCount()):
            item = self.results_table.item(row, col)
            if item:
                item.setBackground(brush)

    def _add_summary_row(self):
        """Insert a bold TOTAL row with summed counts at the bottom of the results table."""
        row_count = self.results_table.rowCount()
        if row_count == 0:
            return

        col_count = self.results_table.columnCount()
        self.results_table.insertRow(row_count)

        # Determine which columns are numeric
        is_sync = self.radio_sync.isChecked()
        if is_sync:
            # Columns: File(0), New(1), Updated(2), Unchanged(3), Deleted(4), Status(5)
            num_cols = range(1, 5)
        else:
            # Columns: File(0), Basic(1), Cloze(2), Status(3), OpenBtn(4)
            num_cols = range(1, 3)

        totals = {}
        for col in num_cols:
            total = 0
            for row in range(row_count):
                item = self.results_table.item(row, col)
                if item:
                    try:
                        total += int(item.text())
                    except ValueError:
                        pass
            totals[col] = total

        # Create TOTAL row with bold font and gray background
        bold_font = QFont()
        bold_font.setBold(True)
        gray_bg = QBrush(QColor("#E0E0E0"))

        total_item = QTableWidgetItem("TOTAL")
        total_item.setFont(bold_font)
        total_item.setBackground(gray_bg)
        self.results_table.setItem(row_count, 0, total_item)

        for col in num_cols:
            item = QTableWidgetItem(str(totals[col]))
            item.setFont(bold_font)
            item.setBackground(gray_bg)
            self.results_table.setItem(row_count, col, item)

        # Fill remaining columns with styled empty cells
        filled_cols = {0} | set(num_cols)
        for col in range(col_count):
            if col not in filled_cols:
                item = QTableWidgetItem("")
                item.setFont(bold_font)
                item.setBackground(gray_bg)
                self.results_table.setItem(row_count, col, item)

    # -- open folder --------------------------------------------------------

    def _open_folder(self, path: str):
        try:
            win_path = subprocess.check_output(
                ["wslpath", "-w", path], text=True,
            ).strip()
            subprocess.Popen(["explorer.exe", win_path])
        except Exception:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_single_folder(self):
        if self._single_output_dir:
            self._open_folder(self._single_output_dir)

    def _on_backup_done(self, wsl_path: str):
        self._backup_dir = wsl_path
        self.open_backup_btn.show()

    def _open_backup_folder(self):
        if self._backup_dir:
            self._open_folder(self._backup_dir)

    # -- details panel ------------------------------------------------------

    def _toggle_details(self):
        if self._details_dialog.isVisible():
            self._details_dialog.hide()
        else:
            self._details_dialog.show()
            self._details_dialog.raise_()

    def _copy_details(self):
        text = self.details_area.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.copy_details_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_details_btn.setText("Copy All"))

    def _append_details(self, text: str):
        self.details_area.moveCursor(QTextCursor.MoveOperation.End)
        self.details_area.insertPlainText(text)
        self.details_area.moveCursor(QTextCursor.MoveOperation.End)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
