"""
Anki export file generation.

Takes parsed note data and produces tab-separated .txt files
ready for Anki's built-in File → Import.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import images
from .parser import ParsedNote, BasicCard, ClozeCard


def _to_single_line(text: str) -> str:
    """Convert newlines to <br> for Anki's one-line-per-card format."""
    return text.replace("\n", "<br>")


def _collect_images(note: ParsedNote) -> set[str]:
    """Collect all unique image references from all cards in the note."""
    all_images = set()

    for card in note.basic_cards:
        all_images.update(images.extract_from_text(card.front))
        all_images.update(images.extract_from_text(card.back))
    for card in note.cloze_cards:
        all_images.update(images.extract_from_text(card.text))

    if all_images:
        print(f"[export] Found {len(all_images)} unique image(s) across all cards")
    else:
        print("[export] No images found in card content")

    return all_images


def _write_basic_file(
    cards: list[BasicCard],
    output_path: Path,
    tags: str,
    dry_run: bool,
) -> None:
    """Write Basic cards to a tab-separated .txt file."""
    print(f"[export] Generating Basic cards file: {output_path.name}")

    if dry_run:
        print(f"[export]   [DRY RUN] Would create: {output_path.name}")
        for i, card in enumerate(cards, 1):
            front = _to_single_line(images.to_anki_syntax(card.front))
            back = _to_single_line(images.to_anki_syntax(card.back))
            print(f"[export]   Card {i}: {front[:60]}...")
        return

    with open(output_path, "w", encoding="utf-8") as f:
        for card in cards:
            front = _to_single_line(images.to_anki_syntax(card.front))
            back = _to_single_line(images.to_anki_syntax(card.back))
            line = f"{front}\t{back}"
            if tags:
                line += f"\t{tags}"
            f.write(line + "\n")

    print(f"[export] Created: {output_path.name} ({len(cards)} cards)")


def _write_cloze_file(
    cards: list[ClozeCard],
    output_path: Path,
    tags: str,
    dry_run: bool,
) -> None:
    """Write Cloze cards to a tab-separated .txt file."""
    print(f"[export] Generating Cloze cards file: {output_path.name}")

    if dry_run:
        print(f"[export]   [DRY RUN] Would create: {output_path.name}")
        for i, card in enumerate(cards, 1):
            text = _to_single_line(images.to_anki_syntax(card.text))
            print(f"[export]   Card {i}: {text[:60]}...")
        return

    with open(output_path, "w", encoding="utf-8") as f:
        for card in cards:
            text = _to_single_line(images.to_anki_syntax(card.text))
            line = text
            if tags:
                line += f"\t{tags}"
            f.write(line + "\n")

    print(f"[export] Created: {output_path.name} ({len(cards)} cards)")


def _print_import_instructions(files_created: list[Path], has_tags: bool) -> None:
    """Print Anki import instructions for the generated files."""
    print()
    print("=" * 60)
    print("  IMPORT INSTRUCTIONS")
    print("=" * 60)

    for f in files_created:
        card_type = "Basic" if "Basic" in f.name else "Cloze"
        step = 1
        print(f"\n  {f.name}:")
        print(f"    {step}. Anki → File → Import"); step += 1
        print(f"    {step}. Select this file"); step += 1
        print(f'    {step}. Set Type to "{card_type}"'); step += 1
        print(f"    {step}. Choose your deck"); step += 1
        if has_tags:
            print(f"    {step}. Map the last field to 'Tags'"); step += 1
        print(f"    {step}. Click Import")


def export(
    note: ParsedNote,
    anki_media_path: str,
    dry_run: bool = False,
    on_step: Callable[[str, str, str], None] | None = None,
) -> list[Path]:
    """
    Export a parsed note to Anki-importable .txt files.

    Pipeline:
    1. Copy images to Anki's media folder
    2. Generate Basic.txt (if Basic cards exist)
    3. Generate Cloze.txt (if Cloze cards exist)
    4. Print import instructions (CLI only)

    When *on_step* is provided it is called as
    ``on_step(step_name, status, detail)`` before and after each step
    so the caller (e.g. the GUI worker) can update progress.

    Returns the list of files created (empty on dry-run or no cards).
    """
    files_created: list[Path] = []

    if not note.basic_cards and not note.cloze_cards:
        print("[export] No flashcards found — nothing to export")
        if on_step:
            on_step("Copy images", "skip", "")
            on_step("Generate Basic.txt", "skip", "")
            on_step("Generate Cloze.txt", "skip", "")
        return files_created

    # -- Copy images --------------------------------------------------------
    if on_step:
        on_step("Copy images", "running", "")
    try:
        print()
        print("--- Step 1: Scan for images ---")
        all_images = _collect_images(note)
        print()
        print("--- Step 2: Copy images to Anki media ---")
        images.copy_to_anki(
            all_images, note.file_path, note.vault_root, anki_media_path, dry_run
        )
        n = len(all_images)
        if on_step:
            on_step("Copy images", "done", f"{n} copied" if n else "none")
    except Exception as e:
        if on_step:
            on_step("Copy images", "error", str(e))

    # -- Generate .txt files ------------------------------------------------
    stem = note.file_path.stem
    output_dir = note.file_path.parent

    # Basic cards
    if note.basic_cards:
        if on_step:
            on_step("Generate Basic.txt", "running", "")
        try:
            print()
            print("--- Step 3: Generate Basic cards ---")
            basic_file = output_dir / f"{stem} - Basic.txt"
            _write_basic_file(note.basic_cards, basic_file, note.tags, dry_run)
            if not dry_run:
                files_created.append(basic_file)
            if on_step:
                on_step("Generate Basic.txt", "done", "")
        except Exception as e:
            if on_step:
                on_step("Generate Basic.txt", "error", str(e))
    else:
        if on_step:
            on_step("Generate Basic.txt", "skip", "")

    # Cloze cards
    if note.cloze_cards:
        if on_step:
            on_step("Generate Cloze.txt", "running", "")
        try:
            step_num = 4 if note.basic_cards else 3
            print()
            print(f"--- Step {step_num}: Generate Cloze cards ---")
            cloze_file = output_dir / f"{stem} - Cloze.txt"
            _write_cloze_file(note.cloze_cards, cloze_file, note.tags, dry_run)
            if not dry_run:
                files_created.append(cloze_file)
            if on_step:
                on_step("Generate Cloze.txt", "done", "")
        except Exception as e:
            if on_step:
                on_step("Generate Cloze.txt", "error", str(e))
    else:
        if on_step:
            on_step("Generate Cloze.txt", "skip", "")

    # Instructions (CLI)
    if files_created:
        _print_import_instructions(files_created, bool(note.tags))

    return files_created
