"""Tests for obsidian_to_anki.config."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

import obsidian_to_anki.config as config_mod


@pytest.fixture(autouse=True)
def _patch_config_file(tmp_path, monkeypatch):
    """Redirect CONFIG_FILE to a temp directory for every test."""
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg)
    return cfg


# ── load ─────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_when_missing(self):
        assert config_mod.load() == {}

    def test_loads_existing_config(self, tmp_path):
        cfg = config_mod.CONFIG_FILE
        cfg.write_text('{"anki_media_path": "/media"}', encoding="utf-8")
        result = config_mod.load()
        assert result["anki_media_path"] == "/media"

    def test_loads_complex_config(self, tmp_path):
        cfg = config_mod.CONFIG_FILE
        data = {"anki_media_path": "/media", "ankiconnect_url": "http://localhost:9999"}
        cfg.write_text(json.dumps(data), encoding="utf-8")
        result = config_mod.load()
        assert result["ankiconnect_url"] == "http://localhost:9999"


# ── save ─────────────────────────────────────────────────────────────────

class TestSave:
    def test_creates_file(self):
        config_mod.save({"key": "value"})
        assert config_mod.CONFIG_FILE.exists()

    def test_round_trip(self):
        data = {"anki_media_path": "/some/path", "extra": 42}
        config_mod.save(data)
        loaded = config_mod.load()
        assert loaded == data

    def test_overwrites_existing(self):
        config_mod.save({"a": 1})
        config_mod.save({"b": 2})
        loaded = config_mod.load()
        assert loaded == {"b": 2}


# ── get_anki_media_path ──────────────────────────────────────────────────

class TestGetAnkiMediaPath:
    def test_cli_override(self, tmp_path):
        media = str(tmp_path / "media")
        result = config_mod.get_anki_media_path(cli_override=media)
        assert result == media
        # Should be saved
        loaded = config_mod.load()
        assert loaded["anki_media_path"] == media

    def test_from_saved_config(self):
        config_mod.save({"anki_media_path": "/saved/path"})
        result = config_mod.get_anki_media_path()
        assert result == "/saved/path"

    def test_interactive_prompt(self, tmp_path, monkeypatch):
        media = str(tmp_path / "prompted_media")
        monkeypatch.setattr("builtins.input", lambda _: media)
        result = config_mod.get_anki_media_path()
        assert result == media
        # Should create the directory
        assert Path(media).exists()

    def test_cli_override_takes_priority(self):
        config_mod.save({"anki_media_path": "/old"})
        result = config_mod.get_anki_media_path(cli_override="/new")
        assert result == "/new"


# ── get_ankiconnect_url ──────────────────────────────────────────────────

class TestGetAnkiconnectUrl:
    def test_default_url(self):
        result = config_mod.get_ankiconnect_url()
        assert result == "http://127.0.0.1:8765"

    def test_cli_override(self):
        result = config_mod.get_ankiconnect_url(cli_override="http://custom:1234")
        assert result == "http://custom:1234"

    def test_from_saved_config(self):
        config_mod.save({"ankiconnect_url": "http://saved:5555"})
        result = config_mod.get_ankiconnect_url()
        assert result == "http://saved:5555"


# ── discover_md_files ────────────────────────────────────────────────────

class TestDiscoverMdFiles:
    def test_finds_md_files(self, tmp_path):
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "b.md").write_text("b")
        (tmp_path / "c.txt").write_text("c")

        result = config_mod.discover_md_files(tmp_path, recursive=False)
        assert len(result) == 2
        names = {f.name for f in result}
        assert names == {"a.md", "b.md"}

    def test_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "top.md").write_text("t")
        (sub / "nested.md").write_text("n")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        names = {f.name for f in result}
        assert "top.md" in names
        assert "nested.md" in names

    def test_non_recursive_ignores_subfolders(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "top.md").write_text("t")
        (sub / "nested.md").write_text("n")

        result = config_mod.discover_md_files(tmp_path, recursive=False)
        assert len(result) == 1
        assert result[0].name == "top.md"

    def test_skips_obsidian_folder(self, tmp_path):
        obs = tmp_path / ".obsidian"
        obs.mkdir()
        (obs / "hidden.md").write_text("h")
        (tmp_path / "visible.md").write_text("v")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        names = {f.name for f in result}
        assert "hidden.md" not in names
        assert "visible.md" in names

    def test_skips_trash_folder(self, tmp_path):
        trash = tmp_path / ".trash"
        trash.mkdir()
        (trash / "deleted.md").write_text("d")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        assert len(result) == 0

    def test_skips_git_folder(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "hook.md").write_text("h")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        assert len(result) == 0

    def test_skips_scripts_folder(self, tmp_path):
        scripts = tmp_path / "Scripts"
        scripts.mkdir()
        (scripts / "tool.md").write_text("t")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        assert len(result) == 0

    def test_skips_templates_folder(self, tmp_path):
        templates = tmp_path / "Templates"
        templates.mkdir()
        (templates / "tmpl.md").write_text("t")

        result = config_mod.discover_md_files(tmp_path, recursive=True)
        assert len(result) == 0

    def test_empty_folder(self, tmp_path):
        assert config_mod.discover_md_files(tmp_path, recursive=False) == []

    def test_returns_sorted(self, tmp_path):
        (tmp_path / "z.md").write_text("z")
        (tmp_path / "a.md").write_text("a")

        result = config_mod.discover_md_files(tmp_path, recursive=False)
        assert result[0].name == "a.md"
        assert result[1].name == "z.md"


# ── Edge cases ──────────────────────────────────────────────────────────

class TestLoadEdgeCases:
    def test_load_malformed_json(self):
        """Corrupted config.json should raise (caller handles it)."""
        config_mod.CONFIG_FILE.write_text("{bad json!!", encoding="utf-8")
        with pytest.raises(Exception):  # json.JSONDecodeError
            config_mod.load()


class TestGetAnkiMediaPathEdgeCases:
    def test_media_path_strips_quotes(self, tmp_path, monkeypatch):
        """User pastes path with surrounding quotes — they should be stripped."""
        media = str(tmp_path / "quoted_media")
        # Simulate user typing: "  '/path/to/media'  "
        monkeypatch.setattr("builtins.input", lambda _: f'  "{media}"  ')
        result = config_mod.get_anki_media_path()
        assert result == media


class TestGetAnkiconnectUrlEdgeCases:
    def test_ankiconnect_url_cli_override_saved(self):
        """CLI override for URL should persist in config."""
        config_mod.get_ankiconnect_url(cli_override="http://custom:9999")
        # Verify it's saved
        loaded = config_mod.load()
        assert loaded["ankiconnect_url"] == "http://custom:9999"
        # Verify subsequent call without override returns the saved value
        result = config_mod.get_ankiconnect_url()
        assert result == "http://custom:9999"
