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
