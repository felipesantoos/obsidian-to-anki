"""Tests for obsidian_to_anki.images."""

import pytest
from pathlib import Path

from obsidian_to_anki.images import (
    extract_from_text,
    resolve_path,
    to_anki_syntax,
    copy_to_anki,
)


# ── extract_from_text ────────────────────────────────────────────────────

class TestExtractFromText:
    def test_obsidian_wiki_link(self):
        assert extract_from_text("![[image.png]]") == ["image.png"]

    def test_obsidian_with_path(self):
        assert extract_from_text("![[subfolder/pic.jpg]]") == ["subfolder/pic.jpg"]

    def test_markdown_image(self):
        assert extract_from_text("![alt](path/photo.png)") == ["path/photo.png"]

    def test_multiple_images(self):
        text = "![[a.png]] and ![b](b.jpg)"
        result = extract_from_text(text)
        assert len(result) == 2
        assert "a.png" in result
        assert "b.jpg" in result

    def test_no_images(self):
        assert extract_from_text("Just plain text") == []

    def test_various_extensions(self):
        for ext in ["png", "jpg", "jpeg", "gif", "bmp", "svg", "webp"]:
            assert len(extract_from_text(f"![[img.{ext}]]")) == 1

    def test_case_insensitive(self):
        assert extract_from_text("![[photo.PNG]]") == ["photo.PNG"]

    def test_ignores_non_image_wiki_links(self):
        assert extract_from_text("![[document.pdf]]") == []

    def test_text_around_images(self):
        text = "Before ![[img.png]] middle ![a](b.jpg) after"
        assert len(extract_from_text(text)) == 2


# ── resolve_path ─────────────────────────────────────────────────────────

class TestResolvePath:
    def test_relative_to_md_file(self, tmp_vault):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        img = tmp_vault / "notes" / "local.png"
        img.write_bytes(b"img")

        result = resolve_path("local.png", md, tmp_vault)
        assert result is not None
        assert result.name == "local.png"

    def test_relative_to_vault_root(self, tmp_vault):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        # diagram.png is in vault/images/
        result = resolve_path("images/diagram.png", md, tmp_vault)
        assert result is not None
        assert result.name == "diagram.png"

    def test_vault_wide_search(self, tmp_vault):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        # diagram.png is in vault/images/ — search by filename only
        result = resolve_path("diagram.png", md, tmp_vault)
        assert result is not None
        assert result.name == "diagram.png"

    def test_not_found_returns_none(self, tmp_vault):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        assert resolve_path("nonexistent.png", md, tmp_vault) is None

    def test_returns_path_object(self, tmp_vault):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        result = resolve_path("diagram.png", md, tmp_vault)
        assert isinstance(result, Path)

    def test_skips_hidden_dirs_in_search(self, tmp_vault):
        hidden = tmp_vault / ".hidden"
        hidden.mkdir()
        (hidden / "secret.png").write_bytes(b"img")
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")

        assert resolve_path("secret.png", md, tmp_vault) is None


# ── to_anki_syntax ───────────────────────────────────────────────────────

class TestToAnkiSyntax:
    def test_obsidian_wiki_link(self):
        assert to_anki_syntax("![[photo.png]]") == '<img src="photo.png">'

    def test_obsidian_with_path(self):
        assert to_anki_syntax("![[sub/photo.png]]") == '<img src="photo.png">'

    def test_markdown_image(self):
        assert to_anki_syntax("![alt](dir/img.jpg)") == '<img src="img.jpg">'

    def test_plain_text_unchanged(self):
        text = "No images here"
        assert to_anki_syntax(text) == text

    def test_mixed_content(self):
        text = "See ![[a.png]] and ![b](c/d.jpg) for details"
        result = to_anki_syntax(text)
        assert '<img src="a.png">' in result
        assert '<img src="d.jpg">' in result
        assert "See" in result
        assert "for details" in result

    def test_multiple_obsidian_images(self):
        text = "![[a.png]] ![[b.png]]"
        result = to_anki_syntax(text)
        assert result.count("<img") == 2


# ── copy_to_anki ─────────────────────────────────────────────────────────

class TestCopyToAnki:
    def test_copies_image(self, tmp_vault, tmp_anki_media):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        refs = {"diagram.png"}

        copy_to_anki(refs, md, tmp_vault, str(tmp_anki_media))

        assert (tmp_anki_media / "diagram.png").exists()

    def test_dry_run_no_copy(self, tmp_vault, tmp_anki_media):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        refs = {"diagram.png"}

        copy_to_anki(refs, md, tmp_vault, str(tmp_anki_media), dry_run=True)

        assert not (tmp_anki_media / "diagram.png").exists()

    def test_empty_refs_no_action(self, tmp_vault, tmp_anki_media):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")

        copy_to_anki(set(), md, tmp_vault, str(tmp_anki_media))
        # No error, no files copied
        assert list(tmp_anki_media.iterdir()) == []

    def test_unresolved_image_skipped(self, tmp_vault, tmp_anki_media):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        refs = {"nonexistent.png"}

        copy_to_anki(refs, md, tmp_vault, str(tmp_anki_media))
        assert not (tmp_anki_media / "nonexistent.png").exists()

    def test_skips_already_in_destination(self, tmp_anki_media):
        """Image already in the media folder should not be re-copied."""
        img = tmp_anki_media / "already.png"
        img.write_bytes(b"img data")

        md = tmp_anki_media / "test.md"
        md.write_text("x")

        # vault_root == anki_media so resolve finds it there
        copy_to_anki({"already.png"}, md, tmp_anki_media, str(tmp_anki_media))
        # Should still exist, no error
        assert img.exists()

    def test_multiple_images(self, tmp_vault, tmp_anki_media):
        md = tmp_vault / "notes" / "test.md"
        md.write_text("x")
        # Create a second image
        (tmp_vault / "images" / "photo.jpg").write_bytes(b"jpg data")

        refs = {"diagram.png", "photo.jpg"}
        copy_to_anki(refs, md, tmp_vault, str(tmp_anki_media))

        assert (tmp_anki_media / "diagram.png").exists()
        assert (tmp_anki_media / "photo.jpg").exists()
