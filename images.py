"""
Image handling.

Detects image references in card content (both Obsidian wiki-links and
standard markdown), resolves them to file paths within the vault, converts
them to Anki's <img> syntax, and copies them to Anki's media folder.
"""

import os
import re
import shutil
from pathlib import Path

# Supported image extensions
IMAGE_EXTENSIONS = r'(?:png|jpg|jpeg|gif|bmp|svg|webp)'

# Regex patterns for image detection
OBSIDIAN_IMAGE_RE = re.compile(
    rf'!\[\[([^\]]+\.{IMAGE_EXTENSIONS})\]\]', re.IGNORECASE
)
MARKDOWN_IMAGE_RE = re.compile(
    rf'!\[[^\]]*\]\(([^)]+\.{IMAGE_EXTENSIONS})\)', re.IGNORECASE
)


def extract_from_text(text: str) -> list[str]:
    """
    Extract all image references from a text string.

    Supports:
        - ![[image.png]]           (Obsidian wiki-link)
        - ![[subfolder/image.png]] (Obsidian wiki-link with path)
        - ![alt](path/image.png)   (standard markdown)
    """
    images = []
    images.extend(m.group(1) for m in OBSIDIAN_IMAGE_RE.finditer(text))
    images.extend(m.group(1) for m in MARKDOWN_IMAGE_RE.finditer(text))
    return images


def resolve_path(image_ref: str, md_file_path: Path, vault_root: Path) -> Path | None:
    """
    Resolve an image reference to an absolute file path.

    Search order:
    1. Relative to the markdown file's directory
    2. Relative to the vault root
    3. Search the entire vault by filename (how Obsidian resolves wiki-links)
    """
    md_dir = md_file_path.resolve().parent

    # Try relative to the markdown file
    candidate = md_dir / image_ref
    if candidate.exists():
        print(f"[images] Resolved '{image_ref}' → {candidate} (relative to note)")
        return candidate

    # Try relative to vault root
    candidate = vault_root / image_ref
    if candidate.exists():
        print(f"[images] Resolved '{image_ref}' → {candidate} (relative to vault)")
        return candidate

    # Search the vault for the filename
    filename = Path(image_ref).name
    for root, dirs, files in os.walk(vault_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if filename in files:
            found = Path(root) / filename
            print(f"[images] Resolved '{image_ref}' → {found} (vault search)")
            return found

    print(f"[images] WARNING: Could not resolve '{image_ref}' — file not found in vault")
    return None


def to_anki_syntax(text: str) -> str:
    """
    Replace Obsidian/markdown image syntax with Anki's <img> tag.

    ![[image.png]]        → <img src="image.png">
    ![alt](path/image.png) → <img src="image.png">
    """
    text = OBSIDIAN_IMAGE_RE.sub(
        lambda m: f'<img src="{Path(m.group(1)).name}">', text
    )
    text = MARKDOWN_IMAGE_RE.sub(
        lambda m: f'<img src="{Path(m.group(1)).name}">', text
    )
    return text


def copy_to_anki(
    image_refs: set[str],
    md_file_path: Path,
    vault_root: Path,
    anki_media_path: str,
    dry_run: bool = False,
) -> None:
    """
    Copy all referenced images to Anki's collection.media folder.

    Resolves each image reference to a file in the vault and copies it.
    Prints status for each image (copied, dry run, or not found).
    """
    if not image_refs:
        print("[images] No images referenced in cards — skipping copy step")
        return

    print(f"[images] {len(image_refs)} image(s) to process:")
    anki_media = Path(anki_media_path)
    copied = 0
    skipped = 0
    not_found = 0

    for img_ref in sorted(image_refs):
        img_path = resolve_path(img_ref, md_file_path, vault_root)
        if img_path:
            dest = anki_media / img_path.name
            if dry_run:
                print(f"[images]   [DRY RUN] Would copy: {img_path.name} → {dest}")
                skipped += 1
            else:
                shutil.copy2(img_path, dest)
                print(f"[images]   Copied: {img_path.name} → {dest}")
                copied += 1
        else:
            not_found += 1

    if dry_run:
        print(f"[images] Dry run complete: {skipped} would be copied, {not_found} not found")
    else:
        print(f"[images] Copy complete: {copied} copied, {not_found} not found")
