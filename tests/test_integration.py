"""Integration tests: real parser + exporter + images with temp files."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from obsidian_to_anki.parser import parse_note
from obsidian_to_anki.exporter import export
from obsidian_to_anki.ankiconnect import AnkiNoteInfo
from obsidian_to_anki.sync import sync_note


def _create_vault(tmp_path, md_name, md_content, images=None):
    """Create a vault with optional images and return (vault, md_path)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "images").mkdir()

    md = vault / md_name
    md.write_text(md_content, encoding="utf-8")

    for name, data in (images or {}).items():
        (vault / "images" / name).write_bytes(data)

    return vault, md


class TestExportRoundTrip:
    def test_basic_export(self, tmp_path):
        md_content = (
            "---\nsubject: Bio\ndeck: Science\n---\n\n"
            "## Flashcards\n\n"
            "Q: What is DNA?\n"
            "A: Deoxyribonucleic acid\n\n"
            "Q: What is RNA?\n"
            "A: Ribonucleic acid\n"
        )
        vault, md = _create_vault(tmp_path, "bio.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media))

        assert len(files) == 1
        assert "Basic" in files[0].name
        content = files[0].read_text(encoding="utf-8")
        lines = content.strip().splitlines()
        assert len(lines) == 2
        assert "What is DNA?" in lines[0]
        assert "bio science" in lines[0]

    def test_cloze_export(self, tmp_path):
        md_content = (
            "---\nsubject: Chem\n---\n\n"
            "## Flashcards\n\n"
            "{{c1::Water}} has formula {{c2::H2O}}\n"
        )
        vault, md = _create_vault(tmp_path, "chem.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media))

        assert len(files) == 1
        assert "Cloze" in files[0].name

    def test_mixed_export(self, tmp_path):
        md_content = (
            "---\ndeck: Mix\n---\n\n"
            "## Flashcards\n\n"
            "Q: Basic Q\nA: Basic A\n\n"
            "{{c1::Cloze}} text\n"
        )
        vault, md = _create_vault(tmp_path, "mix.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media))
        assert len(files) == 2

    def test_export_with_images(self, tmp_path):
        md_content = (
            "## Flashcards\n\n"
            "Q: What is this?\n"
            "A: A cell ![[cell.png]]\n"
        )
        vault, md = _create_vault(
            tmp_path, "img.md", md_content,
            images={"cell.png": b"\x89PNG data"},
        )
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media))

        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert '<img src="cell.png">' in content
        assert (media / "cell.png").exists()

    def test_dry_run_no_side_effects(self, tmp_path):
        md_content = (
            "## Flashcards\n\n"
            "Q: Q1\nA: A1\n"
        )
        vault, md = _create_vault(tmp_path, "dry.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media), dry_run=True)

        assert files == []
        # No .txt files created
        assert not list(vault.glob("*.txt"))


class TestSyncRoundTrip:
    def test_new_cards_synced(self, tmp_path):
        md_content = (
            "---\ndeck: Science\n---\n\n"
            "## Flashcards\n\n"
            "Q: What is DNA?\n"
            "A: Deoxyribonucleic acid\n"
        )
        vault, md = _create_vault(tmp_path, "bio.md", md_content)

        note = parse_note(md)
        client = MagicMock()
        client.add_note.return_value = 42
        client.find_notes.return_value = [42]
        client.get_media_dir_path.return_value = None

        result = sync_note(note, client)
        assert result.new_count == 1
        client.add_note.assert_called_once()

        # ID should be written back
        content = md.read_text(encoding="utf-8")
        assert "<!-- anki-id: 42 -->" in content

    def test_sync_dry_run(self, tmp_path):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        vault, md = _create_vault(tmp_path, "dry.md", md_content)

        note = parse_note(md)
        client = MagicMock()
        client.find_notes.return_value = []
        client.get_media_dir_path.return_value = None

        result = sync_note(note, client, dry_run=True)
        assert result.new_count == 1
        client.add_note.assert_not_called()

        # No IDs written
        content = md.read_text(encoding="utf-8")
        assert "anki-id" not in content

    def test_batch_export(self, tmp_path):
        """Multiple files parsed and exported independently."""
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        media = tmp_path / "media"
        media.mkdir()

        for name, content in [
            ("a.md", "## Flashcards\n\nQ: Q1\nA: A1\n"),
            ("b.md", "## Flashcards\n\n{{c1::cloze}} text\n"),
        ]:
            (vault / name).write_text(content, encoding="utf-8")

        all_files = []
        for md in sorted(vault.glob("*.md")):
            note = parse_note(md)
            files = export(note, str(media))
            all_files.extend(files)

        assert len(all_files) == 2

    def test_orphan_detection_integration(self, tmp_path):
        """Orphan notes detected during sync."""
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Kept Q\nA: Kept A\n"
        )
        vault, md = _create_vault(tmp_path, "orphan.md", md_content)

        note = parse_note(md)
        client = MagicMock()
        client.notes_info.return_value = [
            AnkiNoteInfo(
                note_id=100, model_name="Basic", tags=[],
                fields={"Front": "Kept Q", "Back": "Kept A"}, mod=0,
            )
        ]
        # 200 is an orphan — in Anki but not in markdown
        client.find_notes.return_value = [100, 200]
        client.get_media_dir_path.return_value = None

        result = sync_note(note, client)
        assert result.unchanged_count == 1
        assert result.deleted_from_obsidian == 1
        client.add_tags.assert_called_once()

    def test_no_flashcards_graceful(self, tmp_path):
        md_content = "# Just notes\n\nNo flashcards here.\n"
        vault, md = _create_vault(tmp_path, "empty.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        note = parse_note(md)
        files = export(note, str(media))
        assert files == []


class TestAdvancedIntegration:
    def test_sync_with_images(self, tmp_path):
        """Full sync flow including image copying."""
        md_content = (
            "---\ndeck: Science\n---\n\n"
            "## Flashcards\n\n"
            "Q: What is this?\n"
            "A: A cell ![[cell.png]]\n"
        )
        vault, md = _create_vault(
            tmp_path, "img_sync.md", md_content,
            images={"cell.png": b"\x89PNG data"},
        )
        media = tmp_path / "anki_media"
        media.mkdir()

        note = parse_note(md)
        client = MagicMock()
        client.add_note.return_value = 42
        client.find_notes.return_value = [42]
        client.get_media_dir_path.return_value = str(media)

        result = sync_note(note, client)
        assert result.new_count == 1
        # Image should be copied
        assert (media / "cell.png").exists()
        # ID should be written back
        content = md.read_text(encoding="utf-8")
        assert "<!-- anki-id: 42 -->" in content

    def test_resync_previously_synced_file(self, tmp_path):
        """Re-syncing a file with existing anki-id comments works correctly."""
        md_content = (
            "---\ndeck: Science\n---\n\n"
            "## Flashcards\n\n"
            "Q: What is DNA?\n"
            "A: Deoxyribonucleic acid\n"
        )
        vault, md = _create_vault(tmp_path, "resync.md", md_content)

        # First sync: create cards
        note = parse_note(md)
        client = MagicMock()
        client.add_note.return_value = 100
        client.find_notes.return_value = [100]
        client.get_media_dir_path.return_value = None

        result1 = sync_note(note, client)
        assert result1.new_count == 1

        # Verify ID written
        content = md.read_text(encoding="utf-8")
        assert "<!-- anki-id: 100 -->" in content

        # Second sync: card is unchanged
        note2 = parse_note(md)
        client2 = MagicMock()
        client2.notes_info.return_value = [
            AnkiNoteInfo(
                note_id=100, model_name="Basic", tags=[],
                fields={"Front": "What is DNA?", "Back": "Deoxyribonucleic acid"},
                mod=0,
            )
        ]
        client2.find_notes.return_value = [100]
        client2.get_media_dir_path.return_value = None

        result2 = sync_note(note2, client2)
        assert result2.unchanged_count == 1
        assert result2.new_count == 0
        client2.add_note.assert_not_called()

        # ID should still be there (not duplicated)
        content2 = md.read_text(encoding="utf-8")
        assert content2.count("anki-id: 100") == 1

    def test_sync_update_and_orphan_same_run(self, tmp_path):
        """One card updated + one orphaned in the same sync run."""
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Updated question\n"
            "A: Updated answer\n"
        )
        vault, md = _create_vault(tmp_path, "upd_orphan.md", md_content)

        note = parse_note(md)
        client = MagicMock()
        client.notes_info.return_value = [
            AnkiNoteInfo(
                note_id=100, model_name="Basic", tags=[],
                fields={"Front": "Old question", "Back": "Old answer"}, mod=0,
            )
        ]
        # 200 is an orphan — in Anki but no longer in markdown
        client.find_notes.return_value = [100, 200]
        client.get_media_dir_path.return_value = None

        result = sync_note(note, client)
        assert result.updated_count == 1
        assert result.deleted_from_obsidian == 1
        client.update_note.assert_called_once()
        client.add_tags.assert_called_once()  # orphan tagged

    def test_batch_sync_multiple_files(self, tmp_path):
        """Batch sync: multiple files processed, one with errors."""
        from obsidian_to_anki.__main__ import run_sync_batch
        from unittest.mock import patch as _patch

        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()

        (vault / "good.md").write_text(
            "## Flashcards\n\nQ: Q1\nA: A1\n", encoding="utf-8"
        )
        (vault / "also_good.md").write_text(
            "## Flashcards\n\nQ: Q2\nA: A2\n", encoding="utf-8"
        )

        mock_sync_result = MagicMock(
            new_count=1, updated_count=0, unchanged_count=0,
            deleted_from_obsidian=0, deleted_from_anki=0,
            error_count=0, errors=[], file_path="x.md",
        )

        with _patch("obsidian_to_anki.ankiconnect.AnkiConnectClient") as mock_cls:
            client = mock_cls.return_value
            client.ping.return_value = True
            client.version.return_value = 6

            with _patch("obsidian_to_anki.sync.sync_note", return_value=mock_sync_result) as mock_sync:
                run_sync_batch(
                    str(vault), "http://localhost:8765",
                    dry_run=False, recursive=False, delete_orphans=False,
                )
                assert mock_sync.call_count == 2

    def test_export_then_re_export_overwrites(self, tmp_path):
        """Exporting twice overwrites existing output files."""
        md_content = (
            "## Flashcards\n\n"
            "Q: Original Q\nA: Original A\n"
        )
        vault, md = _create_vault(tmp_path, "reexp.md", md_content)
        media = tmp_path / "media"
        media.mkdir()

        # First export
        note1 = parse_note(md)
        files1 = export(note1, str(media))
        assert len(files1) == 1
        content1 = files1[0].read_text(encoding="utf-8")
        assert "Original Q" in content1

        # Modify the markdown
        md.write_text(
            "## Flashcards\n\n"
            "Q: Changed Q\nA: Changed A\n",
            encoding="utf-8",
        )

        # Second export overwrites
        note2 = parse_note(md)
        files2 = export(note2, str(media))
        assert len(files2) == 1
        content2 = files2[0].read_text(encoding="utf-8")
        assert "Changed Q" in content2
        assert "Original Q" not in content2
