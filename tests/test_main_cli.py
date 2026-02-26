"""Tests for obsidian_to_anki.__main__ (CLI entry point)."""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from obsidian_to_anki.__main__ import (
    main,
    run_single,
    run_batch,
    run_sync_single,
    run_sync_batch,
)


# ── Argument parsing via main() ──────────────────────────────────────────

class TestMainArgParsing:
    @patch("obsidian_to_anki.__main__.run_single")
    @patch("obsidian_to_anki.__main__.get_anki_media_path", return_value="/media")
    def test_single_file(self, mock_media, mock_run, tmp_path, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("x")
        monkeypatch.setattr(sys, "argv", ["prog", str(md)])
        main()
        mock_run.assert_called_once_with(str(md), "/media", dry_run=False)

    @patch("obsidian_to_anki.__main__.run_batch")
    @patch("obsidian_to_anki.__main__.get_anki_media_path", return_value="/media")
    def test_folder(self, mock_media, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path)])
        main()
        mock_run.assert_called_once_with(str(tmp_path), "/media", dry_run=False, recursive=False)

    @patch("obsidian_to_anki.__main__.run_batch")
    @patch("obsidian_to_anki.__main__.get_anki_media_path", return_value="/media")
    def test_recursive_flag(self, mock_media, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "--recursive"])
        main()
        mock_run.assert_called_once_with(str(tmp_path), "/media", dry_run=False, recursive=True)

    @patch("obsidian_to_anki.__main__.run_single")
    @patch("obsidian_to_anki.__main__.get_anki_media_path", return_value="/media")
    def test_dry_run_flag(self, mock_media, mock_run, tmp_path, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("x")
        monkeypatch.setattr(sys, "argv", ["prog", str(md), "--dry-run"])
        main()
        mock_run.assert_called_once_with(str(md), "/media", dry_run=True)

    @patch("obsidian_to_anki.__main__.run_sync_single")
    @patch("obsidian_to_anki.__main__.get_ankiconnect_url", return_value="http://127.0.0.1:8765")
    def test_sync_single(self, mock_url, mock_run, tmp_path, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("x")
        monkeypatch.setattr(sys, "argv", ["prog", str(md), "--sync"])
        main()
        mock_run.assert_called_once()

    @patch("obsidian_to_anki.__main__.run_sync_batch")
    @patch("obsidian_to_anki.__main__.get_ankiconnect_url", return_value="http://127.0.0.1:8765")
    def test_sync_batch(self, mock_url, mock_run, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path), "--sync"])
        main()
        mock_run.assert_called_once()

    @patch("obsidian_to_anki.__main__.run_sync_single")
    @patch("obsidian_to_anki.__main__.get_ankiconnect_url", return_value="http://127.0.0.1:8765")
    def test_delete_orphans_flag(self, mock_url, mock_run, tmp_path, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("x")
        monkeypatch.setattr(sys, "argv", ["prog", str(md), "--sync", "--delete-orphans"])
        main()
        _, kwargs = mock_run.call_args
        assert kwargs.get("delete_orphans") is True or mock_run.call_args[0][-1] is True

    def test_invalid_path_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "/nonexistent/path/xyz123"])
        with pytest.raises(SystemExit):
            main()

    @patch("obsidian_to_anki.__main__.get_anki_media_path", return_value="/media")
    def test_anki_media_cli_override(self, mock_media, tmp_path, monkeypatch):
        md = tmp_path / "note.md"
        md.write_text("x")
        monkeypatch.setattr(sys, "argv", ["prog", str(md), "--anki-media", "/custom/media"])
        with patch("obsidian_to_anki.__main__.run_single"):
            main()
        mock_media.assert_called_once_with("/custom/media")


# ── run_single ───────────────────────────────────────────────────────────

class TestRunSingle:
    @patch("obsidian_to_anki.__main__.export")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_calls_parse_and_export(self, mock_parse, mock_export, tmp_path):
        mock_note = MagicMock()
        mock_parse.return_value = mock_note
        mock_export.return_value = []

        run_single(str(tmp_path / "f.md"), "/media", dry_run=False)

        mock_parse.assert_called_once()
        mock_export.assert_called_once_with(mock_note, "/media", dry_run=False)

    @patch("obsidian_to_anki.__main__.parse_note")
    def test_file_not_found_exits(self, mock_parse):
        mock_parse.side_effect = FileNotFoundError("not found")
        with pytest.raises(SystemExit):
            run_single("/nonexistent.md", "/media", dry_run=False)


# ── run_batch ────────────────────────────────────────────────────────────

class TestRunBatch:
    @patch("obsidian_to_anki.__main__.export")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_processes_all_files(self, mock_parse, mock_export, tmp_path):
        (tmp_path / "a.md").write_text("## Flashcards\n\nQ: Q\nA: A\n")
        (tmp_path / "b.md").write_text("## Flashcards\n\nQ: Q\nA: A\n")
        mock_note = MagicMock()
        mock_parse.return_value = mock_note
        mock_export.return_value = []

        run_batch(str(tmp_path), "/media", dry_run=False)

        assert mock_parse.call_count == 2

    @patch("obsidian_to_anki.__main__.export")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_continues_on_error(self, mock_parse, mock_export, tmp_path):
        (tmp_path / "a.md").write_text("x")
        (tmp_path / "b.md").write_text("x")
        mock_parse.side_effect = [Exception("fail"), MagicMock()]
        mock_export.return_value = []

        run_batch(str(tmp_path), "/media", dry_run=False)
        assert mock_parse.call_count == 2

    def test_empty_folder(self, tmp_path):
        # Should not raise
        run_batch(str(tmp_path), "/media", dry_run=False)


# ── run_sync_single ──────────────────────────────────────────────────────

class TestRunSyncSingle:
    @patch("obsidian_to_anki.sync.sync_note")
    @patch("obsidian_to_anki.ankiconnect.AnkiConnectClient")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_calls_sync(self, mock_parse, mock_client_cls, mock_sync, tmp_path):
        mock_note = MagicMock()
        mock_parse.return_value = mock_note
        client = mock_client_cls.return_value
        client.ping.return_value = True
        client.version.return_value = 6
        mock_sync.return_value = MagicMock(
            new_count=1, updated_count=0, unchanged_count=0,
            deleted_from_obsidian=0, deleted_from_anki=0,
            error_count=0, errors=[], file_path="test.md",
        )

        run_sync_single("test.md", "http://localhost:8765", dry_run=False, delete_orphans=False)
        mock_sync.assert_called_once()

    @patch("obsidian_to_anki.ankiconnect.AnkiConnectClient")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_ping_failure_exits(self, mock_parse, mock_client_cls):
        mock_parse.return_value = MagicMock()
        client = mock_client_cls.return_value
        client.ping.return_value = False

        with pytest.raises(SystemExit):
            run_sync_single("test.md", "http://localhost:8765", False, False)


# ── run_sync_batch ───────────────────────────────────────────────────────

class TestRunSyncBatch:
    @patch("obsidian_to_anki.sync.sync_note")
    @patch("obsidian_to_anki.ankiconnect.AnkiConnectClient")
    @patch("obsidian_to_anki.__main__.parse_note")
    def test_processes_all_files(self, mock_parse, mock_client_cls, mock_sync, tmp_path):
        (tmp_path / "a.md").write_text("x")
        (tmp_path / "b.md").write_text("x")
        mock_parse.return_value = MagicMock()
        client = mock_client_cls.return_value
        client.ping.return_value = True
        client.version.return_value = 6
        mock_sync.return_value = MagicMock(
            new_count=0, updated_count=0, unchanged_count=0,
            deleted_from_obsidian=0, deleted_from_anki=0,
            error_count=0, errors=[], file_path="x.md",
        )

        run_sync_batch(str(tmp_path), "http://localhost:8765", False, False, False)
        assert mock_parse.call_count == 2

    def test_empty_folder(self, tmp_path):
        with patch("obsidian_to_anki.ankiconnect.AnkiConnectClient"):
            run_sync_batch(str(tmp_path), "http://localhost:8765", False, False, False)
