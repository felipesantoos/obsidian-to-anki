"""Tests for obsidian_to_anki.exporter."""

import pytest
from pathlib import Path
from unittest.mock import patch

from obsidian_to_anki.parser import BasicCard, ClozeCard, ParsedNote
from obsidian_to_anki.exporter import (
    _to_single_line,
    _collect_images,
    _write_basic_file,
    _write_cloze_file,
    export,
)


# ── _to_single_line ──────────────────────────────────────────────────────

class TestToSingleLine:
    def test_replaces_newlines(self):
        assert _to_single_line("line1\nline2") == "line1<br>line2"

    def test_no_newlines(self):
        assert _to_single_line("single line") == "single line"

    def test_multiple_newlines(self):
        assert _to_single_line("a\nb\nc") == "a<br>b<br>c"


# ── _collect_images ──────────────────────────────────────────────────────

class TestCollectImages:
    def test_basic_card_images(self, parsed_note_factory):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="![[a.png]]", back="![[b.png]]")]
        )
        result = _collect_images(note)
        assert result == {"a.png", "b.png"}

    def test_cloze_card_images(self, parsed_note_factory):
        note = parsed_note_factory(
            cloze_cards=[ClozeCard(text="See ![[c.png]]")]
        )
        result = _collect_images(note)
        assert result == {"c.png"}

    def test_no_images(self, parsed_note_factory):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")]
        )
        assert _collect_images(note) == set()

    def test_deduplicates(self, parsed_note_factory):
        note = parsed_note_factory(
            basic_cards=[
                BasicCard(front="![[x.png]]", back="![[x.png]]"),
                BasicCard(front="![[x.png]]", back="text"),
            ]
        )
        assert _collect_images(note) == {"x.png"}


# ── _write_basic_file ────────────────────────────────────────────────────

class TestWriteBasicFile:
    def test_creates_file(self, tmp_path):
        cards = [BasicCard(front="Q1", back="A1")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=False)
        assert out.exists()

    def test_tab_separated(self, tmp_path):
        cards = [BasicCard(front="Q1", back="A1")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "Q1\tA1\n" == content

    def test_with_tags(self, tmp_path):
        cards = [BasicCard(front="Q1", back="A1")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="bio science", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "Q1\tA1\tbio science\n" == content

    def test_multiple_cards(self, tmp_path):
        cards = [
            BasicCard(front="Q1", back="A1"),
            BasicCard(front="Q2", back="A2"),
        ]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=False)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_newlines_converted(self, tmp_path):
        cards = [BasicCard(front="Line1\nLine2", back="A")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "Line1<br>Line2" in content
        assert "\n" not in content.split("\t")[0]  # front has no real newlines

    def test_image_conversion(self, tmp_path):
        cards = [BasicCard(front="See ![[img.png]]", back="A")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert '<img src="img.png">' in content

    def test_dry_run_no_file(self, tmp_path):
        cards = [BasicCard(front="Q", back="A")]
        out = tmp_path / "basic.txt"
        _write_basic_file(cards, out, tags="", dry_run=True)
        assert not out.exists()


# ── _write_cloze_file ────────────────────────────────────────────────────

class TestWriteClozeFile:
    def test_creates_file(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Water}} is H2O")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=False)
        assert out.exists()

    def test_content(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Water}} is H2O")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "{{c1::Water}} is H2O\n" == content

    def test_with_tags(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Water}}")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="chem", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "{{c1::Water}}\tchem\n" == content

    def test_dry_run_no_file(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Water}}")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=True)
        assert not out.exists()


# ── export ───────────────────────────────────────────────────────────────

class TestExport:
    def test_basic_only(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            file_name="study.md",
        )
        files = export(note, str(tmp_anki_media))
        assert len(files) == 1
        assert "Basic" in files[0].name

    def test_cloze_only(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            cloze_cards=[ClozeCard(text="{{c1::x}}")],
            file_name="study.md",
        )
        files = export(note, str(tmp_anki_media))
        assert len(files) == 1
        assert "Cloze" in files[0].name

    def test_mixed_creates_both(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            cloze_cards=[ClozeCard(text="{{c1::x}}")],
            file_name="study.md",
        )
        files = export(note, str(tmp_anki_media))
        assert len(files) == 2
        names = {f.name for f in files}
        assert "study - Basic.txt" in names
        assert "study - Cloze.txt" in names

    def test_no_cards_returns_empty(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(file_name="empty.md")
        files = export(note, str(tmp_anki_media))
        assert files == []

    def test_dry_run_returns_empty(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            file_name="study.md",
        )
        files = export(note, str(tmp_anki_media), dry_run=True)
        assert files == []

    def test_on_step_callback(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            file_name="study.md",
        )
        steps = []
        export(note, str(tmp_anki_media), on_step=lambda s, st, d: steps.append((s, st)))
        step_names = [s for s, _ in steps]
        assert "Copy images" in step_names
        assert "Generate Basic.txt" in step_names

    def test_on_step_skip_no_cards(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(file_name="empty.md")
        steps = []
        export(note, str(tmp_anki_media), on_step=lambda s, st, d: steps.append((s, st)))
        statuses = [st for _, st in steps]
        assert all(st == "skip" for st in statuses)

    def test_tags_in_output(self, parsed_note_factory, tmp_anki_media):
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            tags="bio science",
            file_name="tagged.md",
        )
        files = export(note, str(tmp_anki_media))
        content = files[0].read_text(encoding="utf-8")
        assert "bio science" in content


# ── _write_cloze_file (parity tests) ────────────────────────────────────

class TestWriteClozeFileParity:
    def test_cloze_newlines_converted(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Water}} is\ncomposed of H2O")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert "{{c1::Water}} is<br>composed of H2O" in content
        # No raw newlines in the card content (only the trailing \n)
        lines = content.splitlines()
        assert len(lines) == 1

    def test_cloze_image_conversion(self, tmp_path):
        cards = [ClozeCard(text="{{c1::Cell}} looks like ![[cell.png]]")]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=False)
        content = out.read_text(encoding="utf-8")
        assert '<img src="cell.png">' in content
        assert "![[" not in content

    def test_cloze_multiple_cards(self, tmp_path):
        cards = [
            ClozeCard(text="{{c1::Water}} is H2O"),
            ClozeCard(text="{{c1::Carbon}} has 6 protons"),
            ClozeCard(text="{{c1::Oxygen}} is O"),
        ]
        out = tmp_path / "cloze.txt"
        _write_cloze_file(cards, out, tags="", dry_run=False)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3


# ── export error branches ───────────────────────────────────────────────

class TestExportErrorBranches:
    def test_export_image_copy_exception(self, parsed_note_factory, tmp_anki_media):
        """Exception during image copy emits error callback but doesn't crash."""
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            file_name="err.md",
        )
        steps = []
        with patch("obsidian_to_anki.exporter.images.copy_to_anki",
                    side_effect=PermissionError("access denied")):
            files = export(note, str(tmp_anki_media),
                           on_step=lambda s, st, d: steps.append((s, st, d)))
        # Image step should report error
        assert ("Copy images", "error", "access denied") in steps
        # Basic file should still be created
        assert len(files) == 1

    def test_export_basic_write_exception(self, parsed_note_factory, tmp_anki_media):
        """Exception during Basic.txt write emits error callback."""
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            cloze_cards=[ClozeCard(text="{{c1::x}}")],
            file_name="err2.md",
        )
        steps = []
        with patch("obsidian_to_anki.exporter._write_basic_file",
                    side_effect=OSError("disk full")):
            files = export(note, str(tmp_anki_media),
                           on_step=lambda s, st, d: steps.append((s, st, d)))
        # Basic step should report error
        assert any(s == "Generate Basic.txt" and st == "error" for s, st, d in steps)
        # Cloze should still be created
        assert len(files) == 1
        assert "Cloze" in files[0].name

    def test_export_cloze_write_exception(self, parsed_note_factory, tmp_anki_media):
        """Exception during Cloze.txt write emits error callback."""
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            cloze_cards=[ClozeCard(text="{{c1::x}}")],
            file_name="err3.md",
        )
        steps = []
        with patch("obsidian_to_anki.exporter._write_cloze_file",
                    side_effect=OSError("disk full")):
            files = export(note, str(tmp_anki_media),
                           on_step=lambda s, st, d: steps.append((s, st, d)))
        # Cloze step should report error
        assert any(s == "Generate Cloze.txt" and st == "error" for s, st, d in steps)
        # Basic should still be created
        assert len(files) == 1
        assert "Basic" in files[0].name

    def test_export_on_step_error_callbacks(self, parsed_note_factory, tmp_anki_media):
        """All error callbacks include the status 'error' and detail string."""
        note = parsed_note_factory(
            basic_cards=[BasicCard(front="Q", back="A")],
            file_name="cb.md",
        )
        steps = []
        with patch("obsidian_to_anki.exporter.images.copy_to_anki",
                    side_effect=RuntimeError("boom")):
            export(note, str(tmp_anki_media),
                   on_step=lambda s, st, d: steps.append((s, st, d)))
        error_steps = [(s, st, d) for s, st, d in steps if st == "error"]
        assert len(error_steps) == 1
        assert error_steps[0][2] == "boom"
