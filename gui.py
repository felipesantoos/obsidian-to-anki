"""
PySide6 desktop GUI for obsidian_to_anki.

Launch:
    python -m obsidian_to_anki --gui
    python -m obsidian_to_anki.gui
"""

import io
import subprocess
import sys
from pathlib import Path

try:
    from PySide6.QtCore import QThread, Signal, QObject, Qt, QUrl
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
from .exporter import (
    _collect_images,
    _write_basic_file,
    _write_cloze_file,
    _print_import_instructions,
)
from . import images
from . import config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_FOLDERS = {".obsidian", ".trash", ".git", "Scripts", "Templates"}

STEP_NAMES = ["Parse note", "Copy images", "Generate Basic.txt", "Generate Cloze.txt"]

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
# Worker thread
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

        # No cards → skip remaining steps
        if bc == 0 and cc == 0:
            for name in STEP_NAMES[1:]:
                self.step_update.emit(name, "skip", "")
            self.file_done.emit(filename, 0, 0, True, str(note.file_path.parent))
            return

        # Step 2 — Copy images
        self.step_update.emit("Copy images", "running", "")
        try:
            all_images = _collect_images(note)
            images.copy_to_anki(
                all_images, note.file_path, note.vault_root,
                self.anki_media, self.dry_run,
            )
            n = len(all_images)
            self.step_update.emit("Copy images", "done", f"{n} copied" if n else "none")
        except Exception as e:
            self.step_update.emit("Copy images", "error", str(e))

        # Prepare output paths
        stem = note.file_path.stem
        output_dir = note.file_path.parent
        files_created: list[Path] = []

        # Step 3 — Generate Basic.txt
        if bc > 0:
            self.step_update.emit("Generate Basic.txt", "running", "")
            try:
                basic_file = output_dir / f"{stem} - Basic.txt"
                _write_basic_file(note.basic_cards, basic_file, note.tags, self.dry_run)
                if not self.dry_run:
                    files_created.append(basic_file)
                self.step_update.emit("Generate Basic.txt", "done", "")
            except Exception as e:
                self.step_update.emit("Generate Basic.txt", "error", str(e))
        else:
            self.step_update.emit("Generate Basic.txt", "skip", "")

        # Step 4 — Generate Cloze.txt
        if cc > 0:
            self.step_update.emit("Generate Cloze.txt", "running", "")
            try:
                cloze_file = output_dir / f"{stem} - Cloze.txt"
                _write_cloze_file(note.cloze_cards, cloze_file, note.tags, self.dry_run)
                if not self.dry_run:
                    files_created.append(cloze_file)
                self.step_update.emit("Generate Cloze.txt", "done", "")
            except Exception as e:
                self.step_update.emit("Generate Cloze.txt", "error", str(e))
        else:
            self.step_update.emit("Generate Cloze.txt", "skip", "")

        # Import instructions (printed to stdout → details panel)
        if files_created:
            _print_import_instructions(files_created, bool(note.tags))

        self.file_done.emit(filename, bc, cc, True, str(output_dir))

    # -- batch ---------------------------------------------------------------

    def _run_batch(self, folder: Path):
        if self.recursive:
            all_md = sorted(folder.rglob("*.md"))
            md_files = [
                f for f in all_md
                if not any(part in SKIP_FOLDERS for part in f.relative_to(folder).parts)
            ]
        else:
            md_files = sorted(folder.glob("*.md"))

        if not md_files:
            print(f"[batch] No .md files found in: {folder}")
            return

        print(f"[batch] Found {len(md_files)} file(s) to process\n")

        for i, md_file in enumerate(md_files, 1):
            try:
                self._run_single(md_file, i, len(md_files))
            except Exception as e:
                print(f"[error] {md_file.name}: {e}")
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
            self.finished_err.emit(str(e))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Obsidian \u2192 Anki Exporter v{__version__}")
        self.resize(700, 580)

        self._worker: ConvertWorker | None = None
        self._redirector = StdoutRedirector()
        self._redirector.text_written.connect(self._append_details)
        self._is_batch = False
        self._total_files = 0
        self._current_file = ""          # file being processed right now
        self._viewing_file = ""           # file whose steps are displayed
        self._file_steps: dict[str, dict[str, tuple[str, str]]] = {}  # stored per-file step data
        self._single_output_dir = ""

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

        # -- Anki media path ------------------------------------------------
        grp_media = QGroupBox("Anki Media Path")
        h2 = QHBoxLayout(grp_media)
        self.media_edit = QLineEdit()
        self.media_edit.setPlaceholderText("Path to Anki's collection.media folder")
        btn_media = QPushButton("Browse\u2026")
        btn_media.clicked.connect(self._browse_media)
        h2.addWidget(self.media_edit, 1)
        h2.addWidget(btn_media)
        layout.addWidget(grp_media)

        # Pre-fill from config
        cfg = config.load()
        if "anki_media_path" in cfg:
            self.media_edit.setText(cfg["anki_media_path"])

        # -- Options --------------------------------------------------------
        h3 = QHBoxLayout()
        self.chk_dry = QCheckBox("Dry run")
        self.chk_recursive = QCheckBox("Recursive")
        h3.addWidget(self.chk_dry)
        h3.addWidget(self.chk_recursive)
        h3.addStretch()
        layout.addLayout(h3)

        # -- Convert button -------------------------------------------------
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setFixedHeight(36)
        self.btn_convert.clicked.connect(self._start_convert)
        layout.addWidget(self.btn_convert)

        # -- Progress section (step checklist) ------------------------------
        self.progress_section = QWidget()
        prog_lay = QVBoxLayout(self.progress_section)
        prog_lay.setContentsMargins(0, 8, 0, 0)

        self.progress_header = QLabel()
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        prog_lay.addWidget(self.progress_header)

        self.step_rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for name in STEP_NAMES:
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

        layout.addWidget(self.progress_section)
        self.progress_section.hide()

        # -- Open folder button (single-file mode) -------------------------
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
        self.results_table.setHorizontalHeaderLabels(["File", "Basic", "Cloze", "Status", ""])
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.cellClicked.connect(self._on_result_clicked)
        res_lay.addWidget(self.results_table)

        layout.addWidget(self.results_section, 1)
        self.results_section.hide()

        # -- Details panel (collapsible) ------------------------------------
        self.details_btn = QPushButton("\u25B6 Details")
        self.details_btn.setFlat(True)
        self.details_btn.setStyleSheet("text-align: left; padding: 4px;")
        self.details_btn.clicked.connect(self._toggle_details)
        layout.addWidget(self.details_btn)
        self.details_btn.hide()

        self.details_area = QTextEdit()
        self.details_area.setReadOnly(True)
        self.details_area.setFont(QFont("Consolas", 9))
        self.details_area.setFixedHeight(150)
        layout.addWidget(self.details_area)
        self.details_area.hide()

        # Push everything up when hidden sections aren't visible
        layout.addStretch()

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

    # -- conversion ---------------------------------------------------------

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

        # Reset UI state
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
        self.details_btn.setText("\u25B6 Details")
        self.btn_convert.setEnabled(False)

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
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _show_validation_error(self, msg: str):
        self.progress_section.show()
        self.progress_header.setText(f"\u2717 {msg}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #F44336;")
        self._reset_steps()

    def _reset_steps(self):
        for name in STEP_NAMES:
            icon_lbl, _name_lbl, detail_lbl = self.step_rows[name]
            icon_lbl.setText(STEP_ICONS["pending"])
            icon_lbl.setStyleSheet("")
            detail_lbl.setText("")

    def _restore_stdout(self):
        sys.stdout = self._old_stdout

    # -- signal handlers ----------------------------------------------------

    def _on_file_started(self, filename: str, index: int, total: int):
        self._total_files = total
        self._is_batch = total > 1
        self._current_file = filename
        self._viewing_file = filename
        self._file_steps[filename] = {name: ("pending", "") for name in STEP_NAMES}

        self.progress_section.show()
        if self._is_batch:
            self.progress_header.setText(f"Processing: {filename}    ({index}/{total})")
        else:
            self.progress_header.setText(f"Processing: {filename}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")

        self._reset_steps()

        # Show real output filenames in step labels
        stem = Path(filename).stem
        self.step_rows["Generate Basic.txt"][1].setText(f"Generate {stem} - Basic.txt")
        self.step_rows["Generate Cloze.txt"][1].setText(f"Generate {stem} - Cloze.txt")

        if self._is_batch:
            self.results_section.show()

    def _on_step_update(self, step_name: str, status: str, detail: str):
        if step_name not in self.step_rows:
            return

        # Always store
        if self._current_file in self._file_steps:
            self._file_steps[self._current_file][step_name] = (status, detail)

        # Only update UI if viewing the file being processed
        if self._viewing_file == self._current_file:
            icon_lbl, _name_lbl, detail_lbl = self.step_rows[step_name]
            icon_lbl.setText(STEP_ICONS.get(status, STEP_ICONS["pending"]))
            icon_lbl.setStyleSheet(STEP_COLORS.get(status, ""))
            detail_lbl.setText(detail)

    def _on_file_done(self, filename: str, basic_count: int, cloze_count: int,
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

    def _on_done(self):
        self._restore_stdout()

        if not self.progress_section.isVisible():
            # No files were processed (e.g., empty folder)
            self.progress_section.show()
            self.progress_header.setText("No .md files found")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")
        elif self._is_batch:
            exported = 0
            for row in range(self.results_table.rowCount()):
                item = self.results_table.item(row, 3)
                if item and "\u2713" in item.text():
                    exported += 1
            total = self.results_table.rowCount()
            self.progress_header.setText(f"\u2713 Done \u2014 {exported}/{total} files exported")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #4CAF50;")
        else:
            self.progress_header.setText("\u2713 Done")
            self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #4CAF50;")
            if self._single_output_dir:
                self.open_folder_btn.show()

        self.btn_convert.setEnabled(True)

    def _on_error(self, msg: str):
        self._restore_stdout()
        self.progress_section.show()
        self.progress_header.setText(f"\u2717 Error: {msg}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px; color: #F44336;")
        self.btn_convert.setEnabled(True)

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
        for name in STEP_NAMES:
            status, detail = steps.get(name, ("pending", ""))
            icon_lbl, _name_lbl, detail_lbl = self.step_rows[name]
            icon_lbl.setText(STEP_ICONS.get(status, STEP_ICONS["pending"]))
            icon_lbl.setStyleSheet(STEP_COLORS.get(status, ""))
            detail_lbl.setText(detail)
        # Update file-specific step labels
        stem = Path(filename).stem
        self.step_rows["Generate Basic.txt"][1].setText(f"Generate {stem} - Basic.txt")
        self.step_rows["Generate Cloze.txt"][1].setText(f"Generate {stem} - Cloze.txt")
        self.progress_header.setText(f"Steps: {filename}")
        self.progress_header.setStyleSheet("font-weight: bold; font-size: 13px;")

    # -- open folder --------------------------------------------------------

    def _open_folder(self, path: str):
        # WSL: QDesktopServices can't open file:// URLs, use explorer.exe
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
            self.details_btn.setText("\u25B6 Details")
        else:
            self.details_area.show()
            self.details_btn.setText("\u25BC Details")

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
