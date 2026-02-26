"""
Configuration management.

Handles loading/saving the config.json file and first-time setup
for the Anki media folder path.
"""

import json
import os
from pathlib import Path

# Config lives next to the package (in Scripts/)
CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def load() -> dict:
    """Load config from config.json. Returns empty dict if not found."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(config: dict) -> None:
    """Save config to config.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_anki_media_path(cli_override: str = None) -> str:
    """
    Get the Anki collection.media path.

    Priority:
    1. CLI argument (--anki-media)
    2. Saved config
    3. Interactive prompt (first-time setup)

    The resolved path is saved to config.json for future runs.
    """
    config = load()

    if cli_override:
        config["anki_media_path"] = cli_override
        save(config)
        print(f"[config] Anki media path set via CLI: {cli_override}")
        return cli_override

    if "anki_media_path" in config:
        path = config["anki_media_path"]
        print(f"[config] Loaded Anki media path: {path}")
        return path

    # First-time interactive setup
    print("=" * 60)
    print("First-time setup: Anki media folder")
    print("=" * 60)
    print()
    print("Where is your Anki collection.media folder?")
    print()
    print("Common locations:")
    print("  Windows: C:\\Users\\<you>\\AppData\\Roaming\\Anki2\\<profile>\\collection.media")
    print("  Mac:     ~/Library/Application Support/Anki2/<profile>/collection.media")
    print("  Linux:   ~/.local/share/Anki2/<profile>/collection.media")
    print()
    path = input("Paste the full path: ").strip().strip('"').strip("'")

    if not os.path.isdir(path):
        print(f"[config] Warning: '{path}' doesn't exist yet. Creating it...")
        os.makedirs(path, exist_ok=True)

    config["anki_media_path"] = path
    save(config)
    print(f"[config] Saved to {CONFIG_FILE}")
    return path


DEFAULT_ANKICONNECT_URL = "http://127.0.0.1:8765"


def get_ankiconnect_url(cli_override: str = None) -> str:
    """
    Get the AnkiConnect endpoint URL.

    Priority:
    1. CLI argument (--ankiconnect-url)
    2. Saved config
    3. Default: http://127.0.0.1:8765
    """
    config = load()

    if cli_override:
        config["ankiconnect_url"] = cli_override
        save(config)
        print(f"[config] AnkiConnect URL set via CLI: {cli_override}")
        return cli_override

    if "ankiconnect_url" in config:
        url = config["ankiconnect_url"]
        print(f"[config] Loaded AnkiConnect URL: {url}")
        return url

    print(f"[config] Using default AnkiConnect URL: {DEFAULT_ANKICONNECT_URL}")
    return DEFAULT_ANKICONNECT_URL


# ---------------------------------------------------------------------------
# Shared folder-discovery helpers
# ---------------------------------------------------------------------------

SKIP_FOLDERS = {".obsidian", ".trash", ".git", "Scripts", "Templates"}


def discover_md_files(folder: Path, recursive: bool) -> list[Path]:
    """Find markdown files in *folder*, skipping non-note directories."""
    if recursive:
        all_md = sorted(folder.rglob("*.md"))
        return [
            f for f in all_md
            if not any(part in SKIP_FOLDERS for part in f.relative_to(folder).parts)
        ]
    return sorted(folder.glob("*.md"))
