"""
Sync engine for pushing Obsidian flashcards to Anki via AnkiConnect.

Handles diffing, creating/updating notes, orphan detection,
and writing Anki note IDs back into the markdown file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import images
from .ankiconnect import AnkiConnectClient, AnkiConnectError, AnkiNoteInfo
from .parser import BasicCard, ClozeCard, ParsedNote


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class CardAction(Enum):
    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    DELETED_FROM_OBSIDIAN = "deleted_from_obsidian"
    DELETED_FROM_ANKI = "deleted_from_anki"
    ERROR = "error"


@dataclass
class CardSyncDetail:
    action: CardAction
    card_type: str           # "basic" or "cloze"
    anki_note_id: int | None
    summary: str             # truncated front text
    error: str = ""


@dataclass
class SyncResult:
    file_path: str
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    deleted_from_obsidian: int = 0
    deleted_from_anki: int = 0
    error_count: int = 0
    details: list[CardSyncDetail] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex for anki-id comments
# ---------------------------------------------------------------------------

ANKI_ID_RE = re.compile(r'<!--\s*anki-id:\s*(\d+)\s*-->')


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _to_local_path(path: str) -> str:
    """Convert a Windows path to a WSL path if running under WSL."""
    if not path:
        return path
    # Detect Windows-style path (e.g. C:\Users\...)
    is_windows_path = len(path) >= 3 and path[1] == ':' and path[2] in ('\\', '/')
    if is_windows_path and sys.platform == "linux":
        try:
            return subprocess.check_output(
                ["wslpath", "-u", path], text=True,
            ).strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
    return path


# ---------------------------------------------------------------------------
# Card-with-ID parsing
# ---------------------------------------------------------------------------

def parse_cards_with_ids(md_content: str) -> list[tuple[BasicCard | ClozeCard, int | None]]:
    """
    Re-parse the ## Flashcards section, extracting anki-id comments.

    Returns a list of (card, anki_id) tuples where anki_id is None for
    cards that haven't been synced yet.
    """
    # Extract the flashcards section
    match = re.search(
        r'^## Flashcards\s*\n(.*?)(?=^## |\Z)',
        md_content,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []

    section = match.group(1)

    # Split into blocks by blank lines, but preserve anki-id comments
    # Strategy: walk through lines, grouping them into blocks
    lines = section.split('\n')
    blocks: list[tuple[int | None, str]] = []  # (anki_id, block_text)
    current_id: int | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Check if this line is an anki-id comment
        id_match = ANKI_ID_RE.match(stripped)
        if id_match:
            # If we have accumulated lines, flush them as a block
            if current_lines:
                block_text = '\n'.join(current_lines).strip()
                if block_text:
                    blocks.append((current_id, block_text))
                current_lines = []
            current_id = int(id_match.group(1))
            continue

        # Empty line = block separator
        if not stripped:
            if current_lines:
                block_text = '\n'.join(current_lines).strip()
                if block_text:
                    blocks.append((current_id, block_text))
                current_lines = []
                current_id = None
            continue

        current_lines.append(line)

    # Flush remaining
    if current_lines:
        block_text = '\n'.join(current_lines).strip()
        if block_text:
            blocks.append((current_id, block_text))

    # Parse each block into a card
    result: list[tuple[BasicCard | ClozeCard, int | None]] = []
    for anki_id, block in blocks:
        # Skip blockquotes and image-only blocks
        if block.startswith(">"):
            continue
        if re.fullmatch(r'!\[\[.*?\]\]', block):
            continue

        if block.startswith("Q:"):
            card = _parse_qa_block(block)
            if card:
                result.append((card, anki_id))
        elif re.search(r'\{\{c\d+::', block):
            result.append((ClozeCard(text=block), anki_id))

    return result


def _parse_qa_block(block: str) -> BasicCard | None:
    """Parse a Q&A block into a BasicCard (mirrors parser._parse_qa_block)."""
    parts = re.split(r'^A:\s*', block, maxsplit=1, flags=re.MULTILINE)
    if len(parts) != 2:
        return None
    front = parts[0].strip()
    back = parts[1].strip()
    front = re.sub(r'^Q:\s*', '', front)
    if not front or not back:
        return None
    return BasicCard(front=front, back=back)


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------

def _card_to_fields(card: BasicCard | ClozeCard) -> dict[str, str]:
    """Convert an Obsidian card to the Anki field dict (after syntax conversion)."""
    if isinstance(card, BasicCard):
        front = images.to_anki_syntax(card.front).replace("\n", "<br>")
        back = images.to_anki_syntax(card.back).replace("\n", "<br>")
        return {"Front": front, "Back": back}
    else:
        text = images.to_anki_syntax(card.text).replace("\n", "<br>")
        return {"Text": text}


def _fields_match(card: BasicCard | ClozeCard, anki_info: AnkiNoteInfo) -> bool:
    """Compare Obsidian card content against Anki note fields."""
    expected = _card_to_fields(card)
    for key, value in expected.items():
        anki_value = anki_info.fields.get(key, "")
        if value != anki_value:
            return False
    return True


# ---------------------------------------------------------------------------
# Card summary text
# ---------------------------------------------------------------------------

def _card_summary(card: BasicCard | ClozeCard) -> str:
    """Return a short summary of the card for display."""
    if isinstance(card, BasicCard):
        text = card.front
    else:
        text = card.text
    return text[:60] + ("..." if len(text) > 60 else "")


def _card_type(card: BasicCard | ClozeCard) -> str:
    return "basic" if isinstance(card, BasicCard) else "cloze"


def _model_name(card: BasicCard | ClozeCard) -> str:
    return "Basic" if isinstance(card, BasicCard) else "Cloze"


# ---------------------------------------------------------------------------
# Source tag for orphan tracking
# ---------------------------------------------------------------------------

def _source_tag(file_path: Path) -> str:
    """Generate the obsidian-src tag for a file."""
    stem = file_path.stem.lower().replace(" ", "-")
    return f"obsidian-src::{stem}"


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------

def sync_note(
    parsed_note: ParsedNote,
    client: AnkiConnectClient,
    dry_run: bool = False,
    delete_orphans: bool = False,
    on_step: Callable[[str, str, str], None] | None = None,
) -> SyncResult:
    """
    Sync a single parsed note to Anki.

    Steps:
    1. Parse cards with IDs from raw markdown
    2. Fetch notesInfo for all known IDs
    3. For each card: ADD / UPDATE / UNCHANGED
    4. Orphan detection
    5. Write IDs back to markdown
    6. Copy images
    """
    result = SyncResult(file_path=str(parsed_note.file_path))
    deck_name = parsed_note.deck_name
    src_tag = _source_tag(parsed_note.file_path)
    tag_list = [t for t in parsed_note.tags.split() if t] + [src_tag]

    # Step 1: Parse cards with IDs
    if on_step:
        on_step("Parse", "running", "")
    with open(parsed_note.file_path, "r", encoding="utf-8") as f:
        md_content = f.read()
    cards_with_ids = parse_cards_with_ids(md_content)
    if on_step:
        on_step("Parse", "done", f"{len(cards_with_ids)} cards")

    if not cards_with_ids:
        print("[sync] No flashcards found — nothing to sync")
        if on_step:
            for step in ["Connect", "Analyze", "Sync", "Write IDs"]:
                on_step(step, "skip", "")
        return result

    # Step 2: Fetch info for known IDs
    if on_step:
        on_step("Connect", "running", "")
    known_ids = [aid for _, aid in cards_with_ids if aid is not None]
    anki_info_map: dict[int, AnkiNoteInfo] = {}
    if known_ids:
        try:
            infos = client.notes_info(known_ids)
            for info in infos:
                if info.note_id:
                    anki_info_map[info.note_id] = info
        except AnkiConnectError as e:
            result.errors.append(f"Failed to fetch note info: {e}")
            if on_step:
                on_step("Connect", "error", str(e))
            return result
        except Exception as e:
            result.errors.append(f"Unexpected error fetching note info: {e}")
            if on_step:
                on_step("Connect", "error", str(e))
            return result
    if on_step:
        on_step("Connect", "done", f"{len(anki_info_map)} existing")

    # Step 3: Analyze and sync each card
    if on_step:
        on_step("Analyze", "running", "")

    new_card_ids: list[tuple[int, int | None]] = []  # (index, new_id or existing_id)

    for idx, (card, anki_id) in enumerate(cards_with_ids):
        summary = _card_summary(card)
        ctype = _card_type(card)
        model = _model_name(card)
        fields = _card_to_fields(card)

        if anki_id is not None and anki_id in anki_info_map:
            # Card has ID and exists in Anki
            info = anki_info_map[anki_id]
            if _fields_match(card, info):
                # Unchanged
                result.unchanged_count += 1
                result.details.append(CardSyncDetail(
                    action=CardAction.UNCHANGED,
                    card_type=ctype,
                    anki_note_id=anki_id,
                    summary=summary,
                ))
                new_card_ids.append((idx, anki_id))
                print(f"[sync] UNCHANGED: {summary}")
            else:
                # Updated
                if not dry_run:
                    try:
                        client.update_note(anki_id, fields, tags=tag_list)
                    except AnkiConnectError as e:
                        result.error_count += 1
                        result.errors.append(f"Update failed for {anki_id}: {e}")
                        result.details.append(CardSyncDetail(
                            action=CardAction.ERROR,
                            card_type=ctype,
                            anki_note_id=anki_id,
                            summary=summary,
                            error=str(e),
                        ))
                        new_card_ids.append((idx, anki_id))
                        continue
                result.updated_count += 1
                result.details.append(CardSyncDetail(
                    action=CardAction.UPDATED,
                    card_type=ctype,
                    anki_note_id=anki_id,
                    summary=summary,
                ))
                new_card_ids.append((idx, anki_id))
                print(f"[sync] UPDATED: {summary}")

        elif anki_id is not None and anki_id not in anki_info_map:
            # Card has ID but note was deleted from Anki
            result.deleted_from_anki += 1
            result.details.append(CardSyncDetail(
                action=CardAction.DELETED_FROM_ANKI,
                card_type=ctype,
                anki_note_id=anki_id,
                summary=summary,
            ))
            print(f"[sync] DELETED_FROM_ANKI (re-creating): {summary}")
            # Re-create the note
            if not dry_run:
                try:
                    new_id = client.add_note(deck_name, model, fields, tag_list)
                    new_card_ids.append((idx, new_id))
                except AnkiConnectError as e:
                    result.error_count += 1
                    result.errors.append(f"Re-create failed: {e}")
                    new_card_ids.append((idx, None))
            else:
                new_card_ids.append((idx, None))

        else:
            # New card (no ID)
            if not dry_run:
                try:
                    new_id = client.add_note(deck_name, model, fields, tag_list)
                    new_card_ids.append((idx, new_id))
                    result.new_count += 1
                    result.details.append(CardSyncDetail(
                        action=CardAction.NEW,
                        card_type=ctype,
                        anki_note_id=new_id,
                        summary=summary,
                    ))
                    print(f"[sync] NEW ({new_id}): {summary}")
                except AnkiConnectError as e:
                    result.error_count += 1
                    result.errors.append(f"Add failed: {e}")
                    result.details.append(CardSyncDetail(
                        action=CardAction.ERROR,
                        card_type=ctype,
                        anki_note_id=None,
                        summary=summary,
                        error=str(e),
                    ))
                    new_card_ids.append((idx, None))
            else:
                result.new_count += 1
                result.details.append(CardSyncDetail(
                    action=CardAction.NEW,
                    card_type=ctype,
                    anki_note_id=None,
                    summary=summary,
                ))
                new_card_ids.append((idx, None))
                print(f"[sync] NEW (dry-run): {summary}")

    if on_step:
        on_step("Analyze", "done",
                f"{result.new_count} new, {result.updated_count} updated, "
                f"{result.unchanged_count} unchanged")

    # Step 4: Orphan detection
    if on_step:
        on_step("Sync", "running", "checking orphans")

    try:
        all_anki_ids = client.find_notes(f"tag:{src_tag}")
        md_ids = {aid for _, aid in new_card_ids if aid is not None}
        orphan_ids = [nid for nid in all_anki_ids if nid not in md_ids]

        if orphan_ids:
            result.deleted_from_obsidian = len(orphan_ids)
            if delete_orphans and not dry_run:
                client.delete_notes(orphan_ids)
                print(f"[sync] DELETED {len(orphan_ids)} orphan(s) from Anki")
            else:
                if not dry_run:
                    client.add_tags(orphan_ids, "obsidian-orphan")
                action = "would delete" if dry_run and delete_orphans else "tagged obsidian-orphan"
                print(f"[sync] {len(orphan_ids)} orphan(s) ({action})")
                for oid in orphan_ids:
                    result.details.append(CardSyncDetail(
                        action=CardAction.DELETED_FROM_OBSIDIAN,
                        card_type="unknown",
                        anki_note_id=oid,
                        summary=f"orphan note {oid}",
                    ))
    except AnkiConnectError as e:
        result.errors.append(f"Orphan detection failed: {e}")
        print(f"[sync] WARNING: Orphan detection failed: {e}")

    if on_step:
        orphan_msg = f"{result.deleted_from_obsidian} orphans" if result.deleted_from_obsidian else "no orphans"
        on_step("Sync", "done", orphan_msg)

    # Step 5: Write IDs back to markdown
    if on_step:
        on_step("Write IDs", "running", "")

    if not dry_run:
        id_map = {idx: aid for idx, aid in new_card_ids if aid is not None}
        try:
            write_ids_to_markdown(parsed_note.file_path, cards_with_ids, id_map)
            if on_step:
                on_step("Write IDs", "done", f"{len(id_map)} IDs written")
        except Exception as e:
            result.errors.append(f"Write IDs failed: {e}")
            if on_step:
                on_step("Write IDs", "error", str(e))
    else:
        if on_step:
            on_step("Write IDs", "skip", "dry run")

    # Step 6: Copy images to Anki media folder
    all_images: set[str] = set()
    for card, _ in cards_with_ids:
        if isinstance(card, BasicCard):
            all_images.update(images.extract_from_text(card.front))
            all_images.update(images.extract_from_text(card.back))
        else:
            all_images.update(images.extract_from_text(card.text))

    if all_images and not dry_run:
        # Get the media path: try AnkiConnect first, then fall back to config
        media_path = client.get_media_dir_path()
        if media_path:
            media_path = _to_local_path(media_path)
        if not media_path:
            from . import config
            cfg = config.load()
            media_path = cfg.get("anki_media_path")
        if media_path:
            images.copy_to_anki(
                all_images,
                parsed_note.file_path,
                parsed_note.vault_root,
                media_path,
                dry_run,
            )
        else:
            print("[images] WARNING: Could not determine Anki media path — skipping image copy")
            result.errors.append("Could not determine Anki media path (configure it in settings or ensure AnkiConnect is up to date)")

    return result


# ---------------------------------------------------------------------------
# Write IDs to markdown
# ---------------------------------------------------------------------------

def write_ids_to_markdown(
    file_path: Path,
    cards_with_ids: list[tuple[BasicCard | ClozeCard, int | None]],
    id_map: dict[int, int],  # card_index -> anki_note_id
) -> None:
    """
    Read the markdown file, find each card block in the ## Flashcards section,
    and insert/update <!-- anki-id: NNN --> comments before each block.

    Safety: aborts if the number of card blocks in the file doesn't match
    the number of cards we parsed.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the flashcards section
    section_match = re.search(
        r'^(## Flashcards\s*\n)(.*?)(?=^## |\Z)',
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section_match:
        return

    header = section_match.group(1)
    section = section_match.group(2)
    section_start = section_match.start(2)
    section_end = section_match.end(2)

    # Rebuild the section with IDs
    lines = section.split('\n')
    new_lines: list[str] = []
    card_index = 0
    in_block = False
    pending_id_written = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip existing anki-id comments (we'll rewrite them)
        if ANKI_ID_RE.match(stripped):
            i += 1
            continue

        # Empty line
        if not stripped:
            if in_block:
                in_block = False
            new_lines.append(line)
            i += 1
            continue

        # Non-empty line: check if this starts a new card block
        is_card_start = (
            stripped.startswith("Q:") or
            stripped.startswith(">") or
            re.fullmatch(r'!\[\[.*?\]\]', stripped) is not None or
            bool(re.search(r'\{\{c\d+::', stripped))
        )

        # Detect a card block start (first non-empty line after empty/start)
        if not in_block:
            in_block = True

            # Only insert ID for actual card blocks (not blockquotes or image-only)
            is_skippable = stripped.startswith(">") or re.fullmatch(r'!\[\[.*?\]\]', stripped) is not None
            if not is_skippable and (stripped.startswith("Q:") or re.search(r'\{\{c\d+::', stripped)):
                # This is a card block — insert anki-id if we have one
                anki_id = id_map.get(card_index)
                if anki_id is not None:
                    new_lines.append(f"<!-- anki-id: {anki_id} -->")
                card_index += 1

        new_lines.append(line)
        i += 1

    # Rebuild the file content
    new_section = '\n'.join(new_lines)
    new_content = content[:section_start] + new_section + content[section_end:]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[sync] Wrote IDs to {file_path.name}")
