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
