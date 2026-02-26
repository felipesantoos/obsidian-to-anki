"""Tests for obsidian_to_anki.sync."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from obsidian_to_anki.parser import BasicCard, ClozeCard, ParsedNote
from obsidian_to_anki.ankiconnect import AnkiNoteInfo
from obsidian_to_anki.sync import (
    CardAction,
    SyncResult,
    parse_cards_with_ids,
    _card_to_fields,
    _fields_match,
    _card_summary,
    _card_type,
    _model_name,
    _source_tag,
    _to_local_path,
    write_ids_to_markdown,
    sync_note,
)


# ── parse_cards_with_ids ─────────────────────────────────────────────────

class TestParseCardsWithIds:
    def test_basic_card_with_id(self):
        md = (
            "## Flashcards\n\n"
            "<!-- anki-id: 111 -->\n"
            "Q: What is DNA?\n"
            "A: Deoxyribonucleic acid\n"
        )
        result = parse_cards_with_ids(md)
        assert len(result) == 1
        card, aid = result[0]
        assert isinstance(card, BasicCard)
        assert card.front == "What is DNA?"
        assert aid == 111

    def test_card_without_id(self):
        md = "## Flashcards\n\nQ: New Q?\nA: New A\n"
        result = parse_cards_with_ids(md)
        assert len(result) == 1
        _, aid = result[0]
        assert aid is None

    def test_cloze_with_id(self):
        md = (
            "## Flashcards\n\n"
            "<!-- anki-id: 222 -->\n"
            "{{c1::Water}} is H2O\n"
        )
        result = parse_cards_with_ids(md)
        assert len(result) == 1
        card, aid = result[0]
        assert isinstance(card, ClozeCard)
        assert aid == 222

    def test_mixed_cards(self):
        md = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Q1\nA: A1\n\n"
            "Q: Q2\nA: A2\n\n"
            "<!-- anki-id: 300 -->\n"
            "{{c1::cloze}} text\n"
        )
        result = parse_cards_with_ids(md)
        assert len(result) == 3
        assert result[0][1] == 100
        assert result[1][1] is None
        assert result[2][1] == 300

    def test_no_flashcards_section(self):
        md = "# Title\n\nJust content"
        assert parse_cards_with_ids(md) == []

    def test_skips_blockquotes(self):
        md = "## Flashcards\n\n> instruction\n\nQ: Q1\nA: A1\n"
        result = parse_cards_with_ids(md)
        assert len(result) == 1

    def test_skips_image_only(self):
        md = "## Flashcards\n\n![[img.png]]\n\nQ: Q1\nA: A1\n"
        result = parse_cards_with_ids(md)
        assert len(result) == 1


# ── _card_to_fields ──────────────────────────────────────────────────────

class TestCardToFields:
    def test_basic_card(self):
        card = BasicCard(front="Question", back="Answer")
        fields = _card_to_fields(card)
        assert fields == {"Front": "Question", "Back": "Answer"}

    def test_cloze_card(self):
        card = ClozeCard(text="{{c1::Water}} is wet")
        fields = _card_to_fields(card)
        assert fields == {"Text": "{{c1::Water}} is wet"}

    def test_newlines_converted(self):
        card = BasicCard(front="Line1\nLine2", back="A")
        fields = _card_to_fields(card)
        assert fields["Front"] == "Line1<br>Line2"

    def test_images_converted(self):
        card = BasicCard(front="See ![[img.png]]", back="A")
        fields = _card_to_fields(card)
        assert '<img src="img.png">' in fields["Front"]


# ── _fields_match ────────────────────────────────────────────────────────

class TestFieldsMatch:
    def test_matching_basic(self):
        card = BasicCard(front="Q", back="A")
        info = AnkiNoteInfo(note_id=1, model_name="Basic", tags=[],
                            fields={"Front": "Q", "Back": "A"}, mod=0)
        assert _fields_match(card, info) is True

    def test_mismatched_basic(self):
        card = BasicCard(front="Q", back="A")
        info = AnkiNoteInfo(note_id=1, model_name="Basic", tags=[],
                            fields={"Front": "Q", "Back": "B"}, mod=0)
        assert _fields_match(card, info) is False

    def test_matching_cloze(self):
        card = ClozeCard(text="{{c1::x}}")
        info = AnkiNoteInfo(note_id=1, model_name="Cloze", tags=[],
                            fields={"Text": "{{c1::x}}"}, mod=0)
        assert _fields_match(card, info) is True

    def test_missing_field_in_anki(self):
        card = BasicCard(front="Q", back="A")
        info = AnkiNoteInfo(note_id=1, model_name="Basic", tags=[],
                            fields={"Front": "Q"}, mod=0)
        assert _fields_match(card, info) is False


# ── _card_summary / _card_type / _model_name ─────────────────────────────

class TestCardHelpers:
    def test_card_summary_basic(self):
        card = BasicCard(front="Short question", back="A")
        assert _card_summary(card) == "Short question"

    def test_card_summary_truncation(self):
        card = BasicCard(front="x" * 100, back="A")
        result = _card_summary(card)
        assert len(result) == 63  # 60 + "..."
        assert result.endswith("...")

    def test_card_summary_cloze(self):
        card = ClozeCard(text="{{c1::x}} text")
        assert _card_summary(card) == "{{c1::x}} text"

    def test_card_type(self):
        assert _card_type(BasicCard(front="", back="")) == "basic"
        assert _card_type(ClozeCard(text="")) == "cloze"

    def test_model_name(self):
        assert _model_name(BasicCard(front="", back="")) == "Basic"
        assert _model_name(ClozeCard(text="")) == "Cloze"


# ── _source_tag ──────────────────────────────────────────────────────────

class TestSourceTag:
    def test_simple_filename(self):
        assert _source_tag(Path("biology.md")) == "obsidian-src::biology"

    def test_spaces_to_hyphens(self):
        assert _source_tag(Path("Cell Biology.md")) == "obsidian-src::cell-biology"

    def test_uses_stem(self):
        assert _source_tag(Path("/path/to/Notes.md")) == "obsidian-src::notes"


# ── _to_local_path ───────────────────────────────────────────────────────

class TestToLocalPath:
    def test_empty_string(self):
        assert _to_local_path("") == ""

    def test_linux_path_unchanged(self):
        assert _to_local_path("/home/user/media") == "/home/user/media"

    def test_short_string(self):
        assert _to_local_path("ab") == "ab"

    @patch("obsidian_to_anki.sync.sys")
    def test_windows_path_on_non_linux(self, mock_sys):
        mock_sys.platform = "win32"
        assert _to_local_path("C:\\Users\\media") == "C:\\Users\\media"


# ── write_ids_to_markdown ────────────────────────────────────────────────

class TestWriteIdsToMarkdown:
    def test_inserts_ids(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text(
            "# Title\n\n"
            "## Flashcards\n\n"
            "Q: Q1\nA: A1\n\n"
            "Q: Q2\nA: A2\n",
            encoding="utf-8",
        )
        cards = [
            (BasicCard(front="Q1", back="A1"), None),
            (BasicCard(front="Q2", back="A2"), None),
        ]
        id_map = {0: 100, 1: 200}
        write_ids_to_markdown(md, cards, id_map)

        content = md.read_text(encoding="utf-8")
        assert "<!-- anki-id: 100 -->" in content
        assert "<!-- anki-id: 200 -->" in content

    def test_updates_existing_ids(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text(
            "## Flashcards\n\n"
            "<!-- anki-id: 999 -->\n"
            "Q: Q1\nA: A1\n",
            encoding="utf-8",
        )
        cards = [(BasicCard(front="Q1", back="A1"), 999)]
        id_map = {0: 999}
        write_ids_to_markdown(md, cards, id_map)

        content = md.read_text(encoding="utf-8")
        assert content.count("anki-id") == 1

    def test_preserves_non_flashcard_content(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text(
            "---\nsubject: Bio\n---\n\n# Title\n\nSome notes.\n\n"
            "## Flashcards\n\nQ: Q1\nA: A1\n\n## References\n\nRef here\n",
            encoding="utf-8",
        )
        cards = [(BasicCard(front="Q1", back="A1"), None)]
        id_map = {0: 500}
        write_ids_to_markdown(md, cards, id_map)

        content = md.read_text(encoding="utf-8")
        assert "subject: Bio" in content
        assert "# Title" in content
        assert "Some notes." in content
        assert "## References" in content
        assert "Ref here" in content

    def test_no_flashcards_section_noop(self, tmp_path):
        md = tmp_path / "note.md"
        original = "# Title\n\nNo flashcards\n"
        md.write_text(original, encoding="utf-8")

        write_ids_to_markdown(md, [], {})
        assert md.read_text(encoding="utf-8") == original

    def test_cloze_card_ids(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text(
            "## Flashcards\n\n"
            "{{c1::Water}} is H2O\n",
            encoding="utf-8",
        )
        cards = [(ClozeCard(text="{{c1::Water}} is H2O"), None)]
        id_map = {0: 777}
        write_ids_to_markdown(md, cards, id_map)

        content = md.read_text(encoding="utf-8")
        assert "<!-- anki-id: 777 -->" in content

    def test_missing_id_in_map_no_comment(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text(
            "## Flashcards\n\nQ: Q1\nA: A1\n",
            encoding="utf-8",
        )
        cards = [(BasicCard(front="Q1", back="A1"), None)]
        id_map = {}  # no id for card 0
        write_ids_to_markdown(md, cards, id_map)

        content = md.read_text(encoding="utf-8")
        assert "anki-id" not in content


# ── sync_note ────────────────────────────────────────────────────────────

class TestSyncNote:
    def _make_note(self, tmp_path, md_content, file_name="test.md"):
        vault = tmp_path / "vault"
        vault.mkdir(exist_ok=True)
        (vault / ".obsidian").mkdir(exist_ok=True)
        md = vault / file_name
        md.write_text(md_content, encoding="utf-8")
        return ParsedNote(
            file_path=md,
            vault_root=vault,
            basic_cards=[],  # sync_note re-parses from file
            cloze_cards=[],
            tags="bio",
            deck_name="Science",
        )

    def test_new_card_added(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.add_note.return_value = 500

        result = sync_note(note, mock_anki_client)

        assert result.new_count == 1
        mock_anki_client.add_note.assert_called_once()

    def test_unchanged_card(self, tmp_path, mock_anki_client):
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Question\nA: Answer\n"
        )
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.notes_info.return_value = [
            AnkiNoteInfo(
                note_id=100, model_name="Basic", tags=["bio"],
                fields={"Front": "Question", "Back": "Answer"}, mod=0,
            )
        ]

        result = sync_note(note, mock_anki_client)
        assert result.unchanged_count == 1
        assert result.new_count == 0

    def test_updated_card(self, tmp_path, mock_anki_client):
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Updated Q\nA: Updated A\n"
        )
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.notes_info.return_value = [
            AnkiNoteInfo(
                note_id=100, model_name="Basic", tags=[],
                fields={"Front": "Old Q", "Back": "Old A"}, mod=0,
            )
        ]

        result = sync_note(note, mock_anki_client)
        assert result.updated_count == 1
        mock_anki_client.update_note.assert_called_once()

    def test_deleted_from_anki_recreated(self, tmp_path, mock_anki_client):
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 999 -->\n"
            "Q: Q1\nA: A1\n"
        )
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.notes_info.return_value = []  # ID not found in Anki
        mock_anki_client.add_note.return_value = 1000

        result = sync_note(note, mock_anki_client)
        assert result.deleted_from_anki == 1
        mock_anki_client.add_note.assert_called_once()

    def test_dry_run_no_mutations(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)

        result = sync_note(note, mock_anki_client, dry_run=True)
        assert result.new_count == 1
        mock_anki_client.add_note.assert_not_called()

    def test_orphan_detection_tags(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.add_note.return_value = 500
        mock_anki_client.find_notes.return_value = [500, 999]  # 999 is orphan

        result = sync_note(note, mock_anki_client)
        assert result.deleted_from_obsidian == 1
        mock_anki_client.add_tags.assert_called_once()

    def test_orphan_deletion(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.add_note.return_value = 500
        mock_anki_client.find_notes.return_value = [500, 888]

        result = sync_note(note, mock_anki_client, delete_orphans=True)
        assert result.deleted_from_obsidian == 1
        mock_anki_client.delete_notes.assert_called_once_with([888])

    def test_no_cards_returns_early(self, tmp_path, mock_anki_client):
        md_content = "# Title\n\nNo flashcards section\n"
        note = self._make_note(tmp_path, md_content)

        result = sync_note(note, mock_anki_client)
        assert result.new_count == 0
        mock_anki_client.add_note.assert_not_called()

    def test_on_step_callback(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.add_note.return_value = 500

        steps = []
        sync_note(note, mock_anki_client, on_step=lambda s, st, d: steps.append(s))
        assert "Parse" in steps
        assert "Connect" in steps
        assert "Analyze" in steps

    def test_writes_ids_back(self, tmp_path, mock_anki_client):
        md_content = "## Flashcards\n\nQ: Q1\nA: A1\n"
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.add_note.return_value = 42

        sync_note(note, mock_anki_client)

        content = note.file_path.read_text(encoding="utf-8")
        assert "<!-- anki-id: 42 -->" in content

    def test_connect_error_returns_early(self, tmp_path, mock_anki_client):
        from obsidian_to_anki.ankiconnect import AnkiConnectError
        md_content = (
            "## Flashcards\n\n"
            "<!-- anki-id: 100 -->\n"
            "Q: Q1\nA: A1\n"
        )
        note = self._make_note(tmp_path, md_content)
        mock_anki_client.notes_info.side_effect = AnkiConnectError("timeout")

        result = sync_note(note, mock_anki_client)
        assert len(result.errors) > 0
