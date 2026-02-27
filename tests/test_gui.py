"""Tests for obsidian_to_anki.gui worker threads and helpers.

These tests require PySide6 and will be skipped if it is not installed.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

PySide6 = pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    """Create a QApplication instance for the entire test module."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ── StdoutRedirector ────────────────────────────────────────────────────

class TestStdoutRedirector:
    def test_write_emits_signal(self, qapp):
        from obsidian_to_anki.gui import StdoutRedirector
        redirector = StdoutRedirector()
        received = []
        redirector.text_written.connect(received.append)

        redirector.write("hello world")
        assert received == ["hello world"]

    def test_write_empty_string_no_emit(self, qapp):
        from obsidian_to_anki.gui import StdoutRedirector
        redirector = StdoutRedirector()
        received = []
        redirector.text_written.connect(received.append)

        redirector.write("")
        assert received == []

    def test_flush_noop(self, qapp):
        from obsidian_to_anki.gui import StdoutRedirector
        redirector = StdoutRedirector()
        # Should not raise
        redirector.flush()


# ── ConvertWorker ───────────────────────────────────────────────────────

class TestConvertWorker:
    def test_single_file_emits_signals(self, qapp, tmp_path):
        from obsidian_to_anki.gui import ConvertWorker

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        md = vault / "test.md"
        md.write_text(
            "## Flashcards\n\nQ: Q1\nA: A1\n", encoding="utf-8"
        )
        media = tmp_path / "media"
        media.mkdir()

        worker = ConvertWorker(str(md), str(media), dry_run=True, recursive=False)

        file_started = []
        step_updates = []
        file_done = []

        worker.file_started.connect(lambda *args: file_started.append(args))
        worker.step_update.connect(lambda *args: step_updates.append(args))
        worker.file_done.connect(lambda *args: file_done.append(args))

        worker.run()  # Run synchronously (not in a thread)

        assert len(file_started) == 1
        assert file_started[0][0] == "test.md"
        assert len(step_updates) > 0
        assert len(file_done) == 1

    def test_batch_processes_multiple_files(self, qapp, tmp_path):
        from obsidian_to_anki.gui import ConvertWorker

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "a.md").write_text("## Flashcards\n\nQ: Q1\nA: A1\n", encoding="utf-8")
        (vault / "b.md").write_text("## Flashcards\n\n{{c1::x}}\n", encoding="utf-8")
        media = tmp_path / "media"
        media.mkdir()

        worker = ConvertWorker(str(vault), str(media), dry_run=True, recursive=False)

        file_started = []
        worker.file_started.connect(lambda *args: file_started.append(args))

        worker.run()

        assert len(file_started) == 2


# ── SyncWorker ──────────────────────────────────────────────────────────

class TestSyncWorker:
    def test_ping_failure_emits_error(self, qapp, tmp_path):
        from obsidian_to_anki.gui import SyncWorker

        md = tmp_path / "test.md"
        md.write_text("## Flashcards\n\nQ: Q1\nA: A1\n")

        worker = SyncWorker(
            str(md), "http://localhost:99999",
            dry_run=False, recursive=False,
            delete_orphans=False, backup=False,
        )

        errors = []
        worker.finished_err.connect(errors.append)

        with patch("obsidian_to_anki.ankiconnect.AnkiConnectClient") as mock_cls:
            client = mock_cls.return_value
            client.ping.return_value = False
            worker.run()

        assert len(errors) == 1
        assert "Cannot reach" in errors[0]

    def test_backup_flow(self, qapp, tmp_path):
        from obsidian_to_anki.gui import SyncWorker

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        md = vault / "test.md"
        md.write_text("## Flashcards\n\nQ: Q1\nA: A1\n", encoding="utf-8")

        worker = SyncWorker(
            str(md), "http://localhost:8765",
            dry_run=False, recursive=False,
            delete_orphans=False, backup=True,
        )

        backup_paths = []
        worker.backup_done.connect(backup_paths.append)

        with patch("obsidian_to_anki.ankiconnect.AnkiConnectClient") as mock_cls, \
             patch("obsidian_to_anki.sync.sync_note") as mock_sync, \
             patch("subprocess.check_output") as mock_wslpath:

            client = mock_cls.return_value
            client.ping.return_value = True

            # Mock media dir path (Windows-style)
            backup_dir = tmp_path / "backups"
            client.get_media_dir_path.return_value = str(tmp_path / "collection.media")

            # Mock wslpath to return a linux path
            mock_wslpath.return_value = str(backup_dir) + "\n"

            client.deck_names.return_value = ["Default"]
            client.export_package.return_value = True

            mock_sync.return_value = MagicMock(
                new_count=0, updated_count=0, unchanged_count=0,
                deleted_from_obsidian=0, deleted_from_anki=0,
                error_count=0, errors=[], file_path=str(md),
            )

            worker.run()

        assert len(backup_paths) == 1
