"""
Markdown and flashcard parsing.

Handles reading Obsidian markdown files, extracting YAML frontmatter,
finding the vault root, and parsing Q&A and Cloze flashcards from the
## Flashcards section.
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class BasicCard:
    """A Basic (question → answer) flashcard."""
    front: str
    back: str


@dataclass
class ClozeCard:
    """A Cloze (fill-in-the-blank) flashcard."""
    text: str


@dataclass
class ParsedNote:
    """The result of parsing an Obsidian markdown note."""
    file_path: Path
    vault_root: Path
    basic_cards: list[BasicCard]
    cloze_cards: list[ClozeCard]
    tags: str


def find_vault_root(file_path: Path) -> Path:
    """
    Walk up from the file to find the vault root.
    The vault root is the folder containing .obsidian/.
    Falls back to the file's parent directory if not found.
    """
    current = file_path.resolve().parent
    while current != current.parent:
        if (current / ".obsidian").exists():
            print(f"[parser] Vault root found: {current}")
            return current
        current = current.parent

    fallback = file_path.resolve().parent
    print(f"[parser] No .obsidian folder found — using fallback: {fallback}")
    return fallback


def extract_tags(md_content: str) -> str:
    """
    Extract tags from YAML frontmatter.
    Uses the 'subject' and 'deck' fields, lowercased and deduplicated.
    """
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', md_content, re.DOTALL)
    if not frontmatter_match:
        print("[parser] No YAML frontmatter found — skipping tag extraction")
        return ""

    print("[parser] YAML frontmatter detected")
    frontmatter = frontmatter_match.group(1)

    deck_match = re.search(r'^deck:\s*(.+)$', frontmatter, re.MULTILINE)
    deck_tag = deck_match.group(1).strip().lower().replace(" ", "-") if deck_match else ""

    subject_match = re.search(r'^subject:\s*(.+)$', frontmatter, re.MULTILINE)
    subject_tag = subject_match.group(1).strip().lower().replace(" ", "-") if subject_match else ""

    # Deduplicate while preserving order
    tags = []
    seen = set()
    for t in [subject_tag, deck_tag]:
        if t and t != "default" and t not in seen:
            seen.add(t)
            tags.append(t)

    result = " ".join(tags)
    if result:
        print(f"[parser] Tags extracted: {result}")
    else:
        print("[parser] No tags found in frontmatter (subject/deck fields empty or 'default')")

    return result


def _extract_flashcards_section(md_content: str) -> str:
    """
    Extract text between ## Flashcards and the next ## header (or EOF).
    Returns the section body (without the ## Flashcards header itself).
    """
    match = re.search(
        r'^## Flashcards\s*\n(.*?)(?=^## |\Z)',
        md_content,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1)


def _split_into_blocks(section_text: str) -> list[str]:
    """
    Split the flashcards section into blocks separated by blank lines.
    Strips leading/trailing whitespace from each block and removes empty blocks.
    """
    blocks = re.split(r'\n\s*\n', section_text)
    return [b.strip() for b in blocks if b.strip()]


def _parse_qa_block(block: str) -> BasicCard | None:
    """
    Parse a Q&A block into a BasicCard.
    Expects lines starting with Q: for the front and A: for the back.
    Returns None if the block doesn't match the Q&A pattern.
    """
    parts = re.split(r'^A:\s*', block, maxsplit=1, flags=re.MULTILINE)
    if len(parts) != 2:
        return None

    front = parts[0].strip()
    back = parts[1].strip()

    # Strip Q: prefix from front
    front = re.sub(r'^Q:\s*', '', front)

    if not front or not back:
        return None

    return BasicCard(front=front, back=back)


def parse_flashcards(md_content: str) -> tuple[list[BasicCard], list[ClozeCard]]:
    """
    Parse flashcards from the ## Flashcards section.

    Supports two formats:
    - Q&A blocks: Lines starting with Q: and A: → BasicCard
    - Cloze paragraphs: Text containing {{c1::...}} → ClozeCard

    Blocks are separated by blank lines.
    """
    basic_cards = []
    cloze_cards = []

    section = _extract_flashcards_section(md_content)
    if not section:
        print("[parser] No ## Flashcards section found")
        return basic_cards, cloze_cards

    blocks = _split_into_blocks(section)

    for block in blocks:
        # Skip blockquote instructions and image-only blocks
        if block.startswith(">"):
            continue
        if re.fullmatch(r'!\[\[.*?\]\]', block):
            continue

        if block.startswith("Q:"):
            card = _parse_qa_block(block)
            if card:
                basic_cards.append(card)
        elif re.search(r'\{\{c\d+::', block):
            cloze_cards.append(ClozeCard(text=block))

    print(f"[parser] Flashcards parsed: {len(basic_cards)} Basic, {len(cloze_cards)} Cloze")

    if not basic_cards and not cloze_cards:
        print("[parser] WARNING: No flashcards found — check that your ## Flashcards")
        print("         section uses Q:/A: blocks or {{c1::...}} cloze syntax")

    return basic_cards, cloze_cards


def parse_note(file_path: str | Path) -> ParsedNote:
    """
    Parse an Obsidian markdown note and return structured data.

    Reads the file, finds the vault root, extracts tags from frontmatter,
    and parses flashcards from the ## Flashcards section.
    """
    file_path = Path(file_path).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"[parser] Reading file: {file_path.name}")

    vault_root = find_vault_root(file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"[parser] File loaded ({len(content)} chars)")

    tags = extract_tags(content)
    basic_cards, cloze_cards = parse_flashcards(content)

    return ParsedNote(
        file_path=file_path,
        vault_root=vault_root,
        basic_cards=basic_cards,
        cloze_cards=cloze_cards,
        tags=tags,
    )
