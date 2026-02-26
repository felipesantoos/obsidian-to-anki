"""
CLI entry point.

Usage:
    python -m obsidian_to_anki <file>
    python -m obsidian_to_anki <file> --anki-media "/path/to/collection.media"
    python -m obsidian_to_anki <folder>              (batch: .md files in folder)
    python -m obsidian_to_anki <folder> --recursive  (all subfolders too)
    python -m obsidian_to_anki .  --recursive        (entire vault)
    python -m obsidian_to_anki <file> --dry-run
"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import get_anki_media_path
from .parser import parse_note
from .exporter import export


def _print_banner(mode: str, target: str, anki_media: str, dry_run: bool) -> None:
    """Print a startup banner with run configuration."""
    print()
    print("=" * 60)
    print(f"  Obsidian → Anki Exporter v{__version__}")
    print("=" * 60)
    print(f"  Mode:       {mode}")
    print(f"  Target:     {target}")
    print(f"  Anki media: {anki_media}")
    if dry_run:
        print(f"  Dry run:    YES (no files will be created or copied)")
    print("=" * 60)
    print()


def _print_summary(note) -> None:
    """Print a summary of what was parsed from the note."""
    print(f"  File:   {note.file_path.name}")
    print(f"  Vault:  {note.vault_root}")
    print(f"  Basic:  {len(note.basic_cards)} cards")
    print(f"  Cloze:  {len(note.cloze_cards)} cards")
    print(f"  Tags:   {note.tags or '(none)'}")
    print()


def run_single(file_path: str, anki_media: str, dry_run: bool) -> None:
    """Export a single markdown file."""
    _print_banner("Single file", file_path, anki_media, dry_run)

    try:
        note = parse_note(file_path)
    except FileNotFoundError as e:
        print(f"[error] {e}")
        sys.exit(1)

    print("--- Parse summary ---")
    _print_summary(note)

    export(note, anki_media, dry_run=dry_run)

    print()
    print("=" * 60)
    print("  Pipeline complete!")
    print("=" * 60)


def run_batch(folder_path: str, anki_media: str, dry_run: bool, recursive: bool = False) -> None:
    """Export all markdown files in a folder (optionally recursive)."""
    folder = Path(folder_path).resolve()

    # Skip hidden folders and common non-note folders
    skip_folders = {".obsidian", ".trash", ".git", "Scripts", "Templates"}

    if recursive:
        all_md = sorted(folder.rglob("*.md"))
        md_files = [
            f for f in all_md
            if not any(part in skip_folders for part in f.relative_to(folder).parts)
        ]
    else:
        md_files = sorted(folder.glob("*.md"))

    mode = "Recursive (all subfolders)" if recursive else "Batch (folder)"
    _print_banner(mode, str(folder), anki_media, dry_run)

    if not md_files:
        print(f"[batch] No .md files found in: {folder}")
        return

    print(f"[batch] Found {len(md_files)} file(s) to process:")
    for f in md_files:
        rel = f.relative_to(folder)
        print(f"[batch]   - {rel}")
    print()

    success = 0
    errors = 0

    for i, md_file in enumerate(md_files):
        print()
        print(f"{'─' * 60}")
        rel = md_file.relative_to(folder)
        print(f"  File {i + 1}/{len(md_files)}: {rel}")
        print(f"{'─' * 60}")

        try:
            note = parse_note(md_file)
            print("--- Parse summary ---")
            _print_summary(note)
            export(note, anki_media, dry_run=dry_run)
            success += 1
        except Exception as e:
            print(f"[error] Failed to process {md_file.name}: {e}")
            errors += 1

    print()
    print("=" * 60)
    print(f"  Batch complete! {success} succeeded, {errors} failed")
    print("=" * 60)


def main():
    if "--gui" in sys.argv:
        from .gui import main as gui_main
        gui_main()
        return

    parser = argparse.ArgumentParser(
        prog="obsidian_to_anki",
        description="Export Obsidian flashcards to Anki-importable .txt files",
    )
    parser.add_argument(
        "path",
        help="Path to a markdown file or folder (batch mode)",
    )
    parser.add_argument(
        "--anki-media",
        help="Path to Anki's collection.media folder (saved after first use)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be done without creating files or copying images",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process all .md files in subfolders too (skips .obsidian, .trash, Scripts, Templates)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()
    target = Path(args.path)

    anki_media = get_anki_media_path(args.anki_media)

    if target.is_dir():
        run_batch(args.path, anki_media, dry_run=args.dry_run, recursive=args.recursive)
    elif target.is_file():
        run_single(args.path, anki_media, dry_run=args.dry_run)
    else:
        print(f"[error] '{args.path}' is not a valid file or folder.")
        sys.exit(1)


if __name__ == "__main__":
    main()
