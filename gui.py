"""
PySide6 desktop GUI for obsidian_to_anki.

Launch:
    python -m obsidian_to_anki --gui
    python -m obsidian_to_anki.gui
"""

import subprocess
import sys
import traceback
from pathlib import Path

try:
    from PySide6.QtCore import QThread, Signal, QObject, Qt, QUrl, QTimer
    from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPushButton,
        QRadioButton,
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
    finished_ok  = Signal()
    finished_err = Signal(str)

    def __init__(self, path: str, url: str, dry_run: bool, recursive: bool, delete_orphans: bool):
        super().__init__()
        self.path = path
        self.url = url
        self.dry_run = dry_run
        self.recursive = recursive
        self.delete_orphans = delete_orphans

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

        try:
            # Pre-check connection
            client = AnkiConnectClient(self.url)
            if not client.ping():
                self.finished_err.emit(
                    f"Cannot reach AnkiConnect at {self.url}. "
                    "Is Anki running with AnkiConnect installed?"
                )
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
        self.resize(720, 620)

        self._worker: ConvertWorker | SyncWorker | None = None
        self._redirector = StdoutRedirector()
        self._redirector.text_written.connect(self._append_details)
        self._is_batch = False
        self._total_files = 0
        self._current_file = ""
        self._viewing_file = ""
        self._file_steps: dict[str, dict[str, tuple[str, str]]] = {}
        self._single_output_dir = ""
        self._current_step_names: list[str] = EXPORT_STEP_NAMES

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

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
        layout.addWidget(grp_input)

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
        layout.addWidget(grp_mode)

        # -- Anki media path (export mode) ----------------------------------
        self.grp_media = QGroupBox("Anki Media Path")
        h2 = QHBoxLayout(self.grp_media)
        self.media_edit = QLineEdit()
        self.media_edit.setPlaceholderText("Path to Anki's collection.media folder")
        btn_media = QPushButton("Browse\u2026")
        btn_media.clicked.connect(self._browse_media)
        h2.addWidget(self.media_edit, 1)
        h2.addWidget(btn_media)
        layout.addWidget(self.grp_media)

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
        layout.addWidget(self.grp_url)
        self.grp_url.hide()

        # -- Options --------------------------------------------------------
        h3 = QHBoxLayout()
        self.chk_dry = QCheckBox("Dry run")
        self.chk_recursive = QCheckBox("Recursive")
        self.chk_delete_orphans = QCheckBox("Delete orphans")
        h3.addWidget(self.chk_dry)
        h3.addWidget(self.chk_recursive)
        h3.addWidget(self.chk_delete_orphans)
        h3.addStretch()
        layout.addLayout(h3)
        self.chk_delete_orphans.hide()

        # -- Action button --------------------------------------------------
        self.btn_action = QPushButton("Convert")
        self.btn_action.setFixedHeight(36)
        self.btn_action.clicked.connect(self._start_action)
        layout.addWidget(self.btn_action)

        # -- Progress section (step checklist) ------------------------------
        self.progress_section = QWidget()
        prog_lay = QVBoxLayout(self.progress_section)
        prog_lay.setContentsMargins(0, 8, 0, 0)

        self.progress_header = QLabel()
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        prog_lay.addWidget(self.progress_header)

        # Create step rows for both modes (we'll show/hide as needed)
        self.step_rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        self._step_layouts: dict[str, QHBoxLayout] = {}
        all_steps = set(EXPORT_STEP_NAMES) | set(SYNC_STEP_NAMES)
        for name in list(EXPORT_STEP_NAMES) + [s for s in SYNC_STEP_NAMES if s not in EXPORT_STEP_NAMES]:
            row_lay = QHBoxLayout()
            icon_lbl = QLabel(STEP_ICONS["pending"])
            icon_lbl.setFixedWidth(20)
            name_lbl = QLabel(name)
            detail_lbl = QLabel("")
            detail_lbl.setStyleSheet("color: gray;")
            row_lay.addWidget(icon_lbl)
            row_lay.addWidget(name_lbl)
            row_lay.addWidget(detail_lbl, 1)
            prog_lay.addLayout(row_lay)
            self.step_rows[name] = (icon_lbl, name_lbl, detail_lbl)
            self._step_layouts[name] = row_lay

        layout.addWidget(self.progress_section)
        self.progress_section.hide()

        # -- Open folder button (single-file export mode) -------------------
        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.clicked.connect(self._open_single_folder)
        layout.addWidget(self.open_folder_btn)
        self.open_folder_btn.hide()

        # -- Results table --------------------------------------------------
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
        self.results_table.cellClicked.connect(self._on_result_clicked)
        res_lay.addWidget(self.results_table)

        layout.addWidget(self.results_section, 1)
        self.results_section.hide()

        # -- Details panel (collapsible) ------------------------------------
        details_header = QHBoxLayout()
        self.details_btn = QPushButton("\u25B6 Details")
        self.details_btn.setFlat(True)
        self.details_btn.setStyleSheet("text-align: left; padding: 4px;")
        self.details_btn.clicked.connect(self._toggle_details)
        details_header.addWidget(self.details_btn)
        details_header.addStretch()
        self.copy_details_btn = QPushButton("Copy")
        self.copy_details_btn.setFixedWidth(50)
        self.copy_details_btn.clicked.connect(self._copy_details)
        self.copy_details_btn.hide()
        details_header.addWidget(self.copy_details_btn)
        layout.addLayout(details_header)
        self.details_btn.hide()

        self.details_area = QTextEdit()
        self.details_area.setReadOnly(True)
        self.details_area.setFont(QFont("Consolas", 9))
        self.details_area.setFixedHeight(150)
        layout.addWidget(self.details_area)
        self.details_area.hide()

        # Push everything up when hidden sections aren't visible
        layout.addStretch()

        # Initial mode setup
        self._on_mode_changed()

    # -- mode switching -----------------------------------------------------

    def _on_mode_changed(self):
        is_sync = self.radio_sync.isChecked()
        self.grp_media.setVisible(not is_sync)
        self.grp_url.setVisible(is_sync)
        self.chk_delete_orphans.setVisible(is_sync)
        self.btn_action.setText("Sync" if is_sync else "Convert")

        # Update step visibility
        self._current_step_names = SYNC_STEP_NAMES if is_sync else EXPORT_STEP_NAMES
        for name in self.step_rows:
            icon_lbl, name_lbl, detail_lbl = self.step_rows[name]
            visible = name in self._current_step_names
            icon_lbl.setVisible(visible)
            name_lbl.setVisible(visible)
            detail_lbl.setVisible(visible)

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
        )
        self._worker.file_started.connect(self._on_file_started)
        self._worker.step_update.connect(self._on_step_update)
        self._worker.file_done.connect(self._on_sync_file_done)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _reset_ui_state(self):
        self._is_batch = False
        self._total_files = 0
        self._current_file = ""
        self._viewing_file = ""
        self._file_steps.clear()
        self._single_output_dir = ""
        self.open_folder_btn.hide()
        self.details_area.clear()
        self.results_table.setRowCount(0)
        self.results_section.hide()
        self._reset_steps()
        self.progress_section.hide()
        self.details_btn.show()
        self.details_area.hide()
        self.copy_details_btn.hide()
        self.details_btn.setText("\u25B6 Details")
        self.btn_action.setEnabled(False)

    def _show_validation_error(self, msg: str):
        self.progress_section.show()
        self.progress_header.setText(f"\u2717 {msg}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #F44336;")
        self._reset_steps()

    def _reset_steps(self):
        for name in self._current_step_names:
            if name in self.step_rows:
                icon_lbl, _name_lbl, detail_lbl = self.step_rows[name]
                icon_lbl.setText(STEP_ICONS["pending"])
                icon_lbl.setStyleSheet("")
                detail_lbl.setText("")

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
        else:
            self.progress_header.setText(f"Processing: {filename}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")

        self._reset_steps()

        # Update step visibility for current mode
        for name in self.step_rows:
            icon_lbl, name_lbl, detail_lbl = self.step_rows[name]
            visible = name in self._current_step_names
            icon_lbl.setVisible(visible)
            name_lbl.setVisible(visible)
            detail_lbl.setVisible(visible)

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
        """Update the icon, colour, and detail label for a single step row."""
        if step_name not in self.step_rows:
            return
        icon_lbl, _name_lbl, detail_lbl = self.step_rows[step_name]
        icon_lbl.setText(STEP_ICONS.get(status, STEP_ICONS["pending"]))
        icon_lbl.setStyleSheet(STEP_COLORS.get(status, ""))
        detail_lbl.setText(detail)

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
        elif basic_count == 0 and cloze_count == 0:
            status_text = "\u2014 No cards"
        else:
            status_text = "\u2713 Exported"
        self.results_table.setItem(row, 3, QTableWidgetItem(status_text))

        if output_dir:
            btn = QPushButton("Open")
            btn.setFixedWidth(50)
            btn.clicked.connect(lambda _checked, p=output_dir: self._open_folder(p))
            self.results_table.setCellWidget(row, 4, btn)

        done = row + 1
        self.results_header.setText(f"Results    {done}/{self._total_files} files")

    # -- sync file done -----------------------------------------------------

    def _on_sync_file_done(self, filename: str, new_count: int, updated_count: int,
                            unchanged_count: int, deleted_count: int, ok: bool):
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
        elif new_count == 0 and updated_count == 0:
            status_text = "\u2713 Up to date"
        else:
            status_text = "\u2713 Synced"
        self.results_table.setItem(row, 5, QTableWidgetItem(status_text))

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
            total = self.results_table.rowCount()
            ok_count = 0
            for row in range(total):
                last_col = self.results_table.columnCount() - 1
                item = self.results_table.item(row, last_col)
                if item and "\u2713" in item.text():
                    ok_count += 1
            action = "synced" if self.radio_sync.isChecked() else "exported"
            self.progress_header.setText(f"\u2713 Done \u2014 {ok_count}/{total} files {action}")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #4CAF50;")
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
        # Auto-expand details so the user can see the full traceback
        if not self.details_area.isVisible():
            self.details_area.show()
            self.copy_details_btn.show()
            self.details_btn.setText("\u25BC Details")

    # -- results table interaction ------------------------------------------

    def _on_result_clicked(self, row: int, _col: int):
        item = self.results_table.item(row, 0)
        if not item:
            return
        filename = item.text()
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

    # -- details panel ------------------------------------------------------

    def _toggle_details(self):
        if self.details_area.isVisible():
            self.details_area.hide()
            self.copy_details_btn.hide()
            self.details_btn.setText("\u25B6 Details")
        else:
            self.details_area.show()
            self.copy_details_btn.show()
            self.details_btn.setText("\u25BC Details")

    def _copy_details(self):
        text = self.details_area.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.copy_details_btn.setText("Copied!")
            QTimer.singleShot(1500, lambda: self.copy_details_btn.setText("Copy"))

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
