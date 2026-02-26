"""Tests for obsidian_to_anki.parser."""

import pytest
from pathlib import Path

from obsidian_to_anki.parser import (
    BasicCard,
    ClozeCard,
    ParsedNote,
    find_vault_root,
    extract_tags,
    extract_deck_name,
    _extract_flashcards_section,
    _split_into_blocks,
    _parse_qa_block,
    parse_flashcards,
    parse_note,
)


# ── find_vault_root ──────────────────────────────────────────────────────

class TestFindVaultRoot:
    def test_finds_obsidian_folder(self, tmp_path):
        vault = tmp_path / "my_vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        sub = vault / "notes"
        sub.mkdir()
        md = sub / "note.md"
        md.write_text("hi")

        assert find_vault_root(md) == vault

    def test_deeply_nested_file(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        deep = vault / "a" / "b" / "c"
        deep.mkdir(parents=True)
        md = deep / "note.md"
        md.write_text("hi")

        assert find_vault_root(md) == vault

    def test_fallback_when_no_obsidian(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text("hi")

        result = find_vault_root(md)
        assert result == tmp_path

    def test_returns_path_object(self, tmp_path):
        md = tmp_path / "note.md"
        md.write_text("hi")
        assert isinstance(find_vault_root(md), Path)


# ── extract_tags ─────────────────────────────────────────────────────────

class TestExtractTags:
    def test_subject_and_deck(self):
        md = "---\nsubject: Biology\ndeck: Science\n---\ncontent"
        assert extract_tags(md) == "biology science"

    def test_subject_only(self):
        md = "---\nsubject: Math\n---\ncontent"
        assert extract_tags(md) == "math"

    def test_deck_only(self):
        md = "---\ndeck: History\n---\ncontent"
        assert extract_tags(md) == "history"

    def test_no_frontmatter(self):
        md = "# Just a heading\nSome text"
        assert extract_tags(md) == ""

    def test_empty_frontmatter(self):
        md = "---\n---\ncontent"
        assert extract_tags(md) == ""

    def test_default_deck_excluded(self):
        md = "---\ndeck: Default\n---\ncontent"
        assert extract_tags(md) == ""

    def test_spaces_replaced_with_hyphens(self):
        md = "---\nsubject: Organic Chemistry\n---\n"
        assert extract_tags(md) == "organic-chemistry"

    def test_deduplication(self):
        md = "---\nsubject: Science\ndeck: Science\n---\n"
        assert extract_tags(md) == "science"


# ── extract_deck_name ────────────────────────────────────────────────────

class TestExtractDeckName:
    def test_returns_deck(self):
        md = "---\ndeck: Biology\n---\ncontent"
        assert extract_deck_name(md) == "Biology"

    def test_preserves_case(self):
        md = "---\ndeck: Organic Chemistry\n---\n"
        assert extract_deck_name(md) == "Organic Chemistry"

    def test_default_when_no_frontmatter(self):
        md = "# heading\ncontent"
        assert extract_deck_name(md) == "Default"

    def test_default_when_no_deck_field(self):
        md = "---\nsubject: Bio\n---\ncontent"
        assert extract_deck_name(md) == "Default"

    def test_default_value_returns_default(self):
        md = "---\ndeck: Default\n---\ncontent"
        assert extract_deck_name(md) == "Default"

    def test_empty_deck_field(self):
        md = "---\ndeck: \n---\ncontent"
        assert extract_deck_name(md) == "Default"


# ── _extract_flashcards_section ──────────────────────────────────────────

class TestExtractFlashcardsSection:
    def test_extracts_section(self):
        md = "# Title\n\n## Flashcards\n\nQ: Q1\nA: A1\n\n## References\n"
        result = _extract_flashcards_section(md)
        assert "Q: Q1" in result
        assert "References" not in result

    def test_section_to_eof(self):
        md = "## Flashcards\n\nQ: Q1\nA: A1\n"
        result = _extract_flashcards_section(md)
        assert "Q: Q1" in result

    def test_no_section_returns_empty(self):
        md = "# Title\n\nSome content\n"
        assert _extract_flashcards_section(md) == ""

    def test_empty_section(self):
        md = "## Flashcards\n\n## Next Section\n"
        result = _extract_flashcards_section(md)
        assert result.strip() == ""


# ── _split_into_blocks ───────────────────────────────────────────────────

class TestSplitIntoBlocks:
    def test_splits_by_blank_lines(self):
        text = "block1 line1\nblock1 line2\n\nblock2 line1\n"
        blocks = _split_into_blocks(text)
        assert len(blocks) == 2

    def test_strips_whitespace(self):
        text = "  block1  \n\n  block2  \n"
        blocks = _split_into_blocks(text)
        assert blocks[0] == "block1"
        assert blocks[1] == "block2"

    def test_removes_empty_blocks(self):
        text = "\n\n\nblock1\n\n\n"
        blocks = _split_into_blocks(text)
        assert len(blocks) == 1


# ── _parse_qa_block ──────────────────────────────────────────────────────

class TestParseQABlock:
    def test_basic_qa(self):
        block = "Q: What is DNA?\nA: Deoxyribonucleic acid"
        card = _parse_qa_block(block)
        assert card.front == "What is DNA?"
        assert card.back == "Deoxyribonucleic acid"

    def test_multiline_answer(self):
        block = "Q: Explain mitosis.\nA: Cell division\ninto two identical cells"
        card = _parse_qa_block(block)
        assert card.front == "Explain mitosis."
        assert "two identical cells" in card.back

    def test_no_answer_returns_none(self):
        block = "Q: Just a question"
        assert _parse_qa_block(block) is None

    def test_empty_front_returns_none(self):
        block = "Q: \nA: Some answer"
        assert _parse_qa_block(block) is None


# ── parse_flashcards ─────────────────────────────────────────────────────

class TestParseFlashcards:
    def test_basic_cards(self, sample_basic_md):
        basic, cloze = parse_flashcards(sample_basic_md)
        assert len(basic) == 2
        assert len(cloze) == 0
        assert basic[0].front == "What is DNA?"

    def test_cloze_cards(self, sample_cloze_md):
        basic, cloze = parse_flashcards(sample_cloze_md)
        assert len(basic) == 0
        assert len(cloze) == 2
        assert "{{c1::Water}}" in cloze[0].text

    def test_mixed_cards(self, sample_mixed_md):
        basic, cloze = parse_flashcards(sample_mixed_md)
        assert len(basic) == 1
        assert len(cloze) == 1

    def test_no_flashcards_section(self):
        md = "# Title\n\nSome content"
        basic, cloze = parse_flashcards(md)
        assert basic == []
        assert cloze == []

    def test_skips_blockquotes(self):
        md = "## Flashcards\n\n> This is an instruction\n\nQ: Real Q?\nA: Real A\n"
        basic, cloze = parse_flashcards(md)
        assert len(basic) == 1

    def test_skips_image_only_blocks(self):
        md = "## Flashcards\n\n![[diagram.png]]\n\nQ: Question?\nA: Answer\n"
        basic, cloze = parse_flashcards(md)
        assert len(basic) == 1

    def test_empty_flashcards_section(self):
        md = "## Flashcards\n\n## Next\n"
        basic, cloze = parse_flashcards(md)
        assert basic == []
        assert cloze == []

    def test_multiline_qa(self):
        md = (
            "## Flashcards\n\n"
            "Q: What are the phases of mitosis?\n"
            "A: Prophase\nMetaphase\nAnaphase\nTelophase\n"
        )
        basic, cloze = parse_flashcards(md)
        assert len(basic) == 1
        assert "Telophase" in basic[0].back


# ── parse_note ───────────────────────────────────────────────────────────

class TestParseNote:
    def test_parses_file(self, tmp_vault):
        md = tmp_vault / "notes" / "biology.md"
        note = parse_note(md)

        assert isinstance(note, ParsedNote)
        assert note.vault_root == tmp_vault
        assert len(note.basic_cards) == 2
        assert note.tags == "biology science"
        assert note.deck_name == "Science"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_note(tmp_path / "nonexistent.md")

    def test_string_path_accepted(self, tmp_vault):
        md = tmp_vault / "notes" / "biology.md"
        note = parse_note(str(md))
        assert isinstance(note, ParsedNote)

    def test_no_cards_still_returns(self, tmp_path):
        vault = tmp_path / "v"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        md = vault / "empty.md"
        md.write_text("# No flashcards here\n", encoding="utf-8")

        note = parse_note(md)
        assert note.basic_cards == []
        assert note.cloze_cards == []

    def test_deck_defaults_to_default(self, tmp_path):
        vault = tmp_path / "v"
        vault.mkdir()
        (vault / ".obsidian").mkdir()
        md = vault / "nodeck.md"
        md.write_text("## Flashcards\n\nQ: Q1\nA: A1\n", encoding="utf-8")

        note = parse_note(md)
        assert note.deck_name == "Default"
