"""Shared fixtures for obsidian_to_anki tests."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from obsidian_to_anki.parser import BasicCard, ClozeCard, ParsedNote


# ---------------------------------------------------------------------------
# Vault / filesystem fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal Obsidian vault structure with sample files."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    (vault / "notes").mkdir()
    (vault / "images").mkdir()

    # Sample image
    img = vault / "images" / "diagram.png"
    img.write_bytes(b"\x89PNG fake image data")

    # Sample basic markdown
    md = vault / "notes" / "biology.md"
    md.write_text(
        "---\nsubject: Biology\ndeck: Science\n---\n\n"
        "# Biology Notes\n\nSome content.\n\n"
        "## Flashcards\n\n"
        "Q: What is DNA?\n"
        "A: Deoxyribonucleic acid\n\n"
        "Q: What is RNA?\n"
        "A: Ribonucleic acid\n",
        encoding="utf-8",
    )

    return vault


@pytest.fixture
def tmp_anki_media(tmp_path):
    """Create an empty directory to act as Anki's collection.media."""
    media = tmp_path / "collection.media"
    media.mkdir()
    return media


# ---------------------------------------------------------------------------
# Markdown content fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_basic_md():
    return (
        "---\nsubject: Biology\ndeck: Science\n---\n\n"
        "# Biology\n\n"
        "## Flashcards\n\n"
        "Q: What is DNA?\n"
        "A: Deoxyribonucleic acid\n\n"
        "Q: What is RNA?\n"
        "A: Ribonucleic acid\n"
    )


@pytest.fixture
def sample_cloze_md():
    return (
        "---\nsubject: Chemistry\ndeck: Science\n---\n\n"
        "## Flashcards\n\n"
        "{{c1::Water}} is composed of {{c2::hydrogen}} and oxygen.\n\n"
        "The atomic number of {{c1::Carbon}} is {{c2::6}}.\n"
    )


@pytest.fixture
def sample_mixed_md():
    return (
        "---\nsubject: Physics\ndeck: Science\n---\n\n"
        "## Flashcards\n\n"
        "Q: What is F=ma?\n"
        "A: Newton's second law\n\n"
        "{{c1::Gravity}} accelerates objects at {{c2::9.8}} m/s².\n"
    )


@pytest.fixture
def sample_md_with_images():
    return (
        "---\nsubject: Bio\ndeck: Science\n---\n\n"
        "## Flashcards\n\n"
        "Q: Identify this structure\n"
        "A: It is a cell ![[cell.png]]\n\n"
        "Q: What does this diagram show?\n"
        "A: Photosynthesis ![diagram](images/diagram.png)\n"
    )


@pytest.fixture
def sample_md_with_ids():
    return (
        "---\nsubject: Bio\ndeck: Science\n---\n\n"
        "## Flashcards\n\n"
        "<!-- anki-id: 111 -->\n"
        "Q: What is DNA?\n"
        "A: Deoxyribonucleic acid\n\n"
        "Q: What is RNA?\n"
        "A: Ribonucleic acid\n"
    )


# ---------------------------------------------------------------------------
# Mock AnkiConnect client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_anki_client():
    """Return a MagicMock mimicking AnkiConnectClient."""
    client = MagicMock()
    client.ping.return_value = True
    client.version.return_value = 6
    client.deck_names.return_value = ["Default", "Science"]
    client.model_names.return_value = ["Basic", "Cloze"]
    client.find_notes.return_value = []
    client.notes_info.return_value = []
    client.add_note.return_value = 12345
    client.get_media_dir_path.return_value = None
    return client


# ---------------------------------------------------------------------------
# ParsedNote factory
# ---------------------------------------------------------------------------

@pytest.fixture
def parsed_note_factory(tmp_vault):
    """Factory to build ParsedNote objects with custom cards/tags."""

    def _make(
        basic_cards=None,
        cloze_cards=None,
        tags="",
        deck_name="Default",
        file_name="test.md",
    ):
        fp = tmp_vault / "notes" / file_name
        if not fp.exists():
            fp.write_text("# placeholder", encoding="utf-8")
        return ParsedNote(
            file_path=fp,
            vault_root=tmp_vault,
            basic_cards=basic_cards or [],
            cloze_cards=cloze_cards or [],
            tags=tags,
            deck_name=deck_name,
        )

    return _make
