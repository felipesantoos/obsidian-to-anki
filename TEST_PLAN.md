# Automated Test Plan — Obsidian to Anki

**Framework:** `pytest` + `pytest-cov`
**Mocking:** `unittest.mock` (stdlib)
**Fixture directory:** `tests/fixtures/` (sample markdown files, images, config)
**Target:** 100% of non-GUI logic (GUI excluded — requires PySide6 event loop)

---

## Directory Structure

```
tests/
├── conftest.py                  # Shared fixtures (tmp vault, tmp anki media, sample markdown)
├── fixtures/
│   ├── vault/                   # Fake Obsidian vault
│   │   ├── .obsidian/           # Empty dir so find_vault_root works
│   │   ├── notes/
│   │   │   ├── basic_only.md
│   │   │   ├── cloze_only.md
│   │   │   ├── mixed_cards.md
│   │   │   ├── no_flashcards.md
│   │   │   ├── no_frontmatter.md
│   │   │   ├── empty_file.md
│   │   │   ├── with_images.md
│   │   │   ├── with_synced_ids.md
│   │   │   └── malformed.md
│   │   └── images/
│   │       ├── diagram.png
│   │       └── photo.jpg
│   └── no_vault/                # Folder WITHOUT .obsidian (fallback test)
│       └── orphan.md
├── test_parser.py
├── test_images.py
├── test_exporter.py
├── test_ankiconnect.py
├── test_sync.py
├── test_config.py
├── test_main_cli.py
└── test_integration.py
```

---

## Shared Fixtures (`conftest.py`)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `tmp_vault` | function | Creates a temp dir with `.obsidian/`, sample `.md` files, and images |
| `tmp_anki_media` | function | Empty temp dir simulating Anki's `collection.media` |
| `sample_basic_md` | function | Returns markdown string with only Q&A cards |
| `sample_cloze_md` | function | Returns markdown string with only cloze cards |
| `sample_mixed_md` | function | Returns markdown string with both card types |
| `sample_md_with_images` | function | Markdown referencing `![[diagram.png]]` and `![alt](photo.jpg)` |
| `sample_md_with_ids` | function | Markdown with `<!-- anki-id: 12345 -->` comments |
| `mock_anki_client` | function | `MagicMock` of `AnkiConnectClient` with sane defaults |
| `parsed_note_factory` | function | Factory function to build `ParsedNote` with custom cards/tags |

---

## 1. `test_parser.py` — Markdown & Flashcard Parsing

### 1.1 `find_vault_root()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Finds vault root from nested file | `vault/notes/basic.md` | Returns `vault/` (parent of `.obsidian/`) |
| 2 | Finds vault root from direct child | `vault/top_level.md` | Returns `vault/` |
| 3 | Falls back to parent dir when no `.obsidian` | `no_vault/orphan.md` | Returns `no_vault/` |
| 4 | Resolves symlinks | symlinked `.md` path | Returns resolved vault root |

### 1.2 `extract_tags()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Extracts subject and deck tags | `---\nsubject: Biology\ndeck: Science\n---` | `"biology science"` |
| 2 | Deduplicates identical tags | `---\nsubject: Math\ndeck: Math\n---` | `"math"` |
| 3 | Skips `default` deck tag | `---\nsubject: Bio\ndeck: Default\n---` | `"bio"` |
| 4 | Returns empty for no frontmatter | `# Just a heading\nSome text` | `""` |
| 5 | Returns empty when both fields missing | `---\ntitle: Note\n---` | `""` |
| 6 | Handles spaces in tag values | `---\nsubject: Organic Chemistry\n---` | `"organic-chemistry"` |
| 7 | Case-insensitive default detection | `---\ndeck: DEFAULT\n---` | `""` |
| 8 | Preserves order (subject before deck) | `---\ndeck: B\nsubject: A\n---` | `"a b"` |

### 1.3 `extract_deck_name()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Extracts custom deck name | `---\ndeck: Science::Biology\n---` | `"Science::Biology"` |
| 2 | Preserves case | `---\ndeck: My Deck\n---` | `"My Deck"` |
| 3 | Returns "Default" when no frontmatter | plain text | `"Default"` |
| 4 | Returns "Default" when deck is default | `---\ndeck: default\n---` | `"Default"` |
| 5 | Returns "Default" when deck field empty | `---\ndeck: \n---` | `"Default"` |
| 6 | Returns "Default" when deck field missing | `---\nsubject: Bio\n---` | `"Default"` |

### 1.4 `_extract_flashcards_section()` (private, test via `parse_flashcards`)

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Extracts section between `## Flashcards` and next `##` | Full note with multiple sections | Only flashcard content |
| 2 | Extracts section to EOF when no following `##` | Note ending after flashcards | All content after header |
| 3 | Returns empty when no `## Flashcards` header | Note without flashcards section | Empty / 0 cards |
| 4 | Ignores `### Flashcards` (wrong level) | Note with `### Flashcards` | 0 cards |

### 1.5 `parse_flashcards()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Parses single Q&A card | `## Flashcards\n\nQ: What?\nA: This.` | 1 BasicCard |
| 2 | Parses multiple Q&A cards | 3 Q/A blocks separated by blank lines | 3 BasicCards |
| 3 | Parses single cloze card | `## Flashcards\n\n{{c1::word}} in sentence` | 1 ClozeCard |
| 4 | Parses multiple cloze cards | 2 cloze blocks | 2 ClozeCards |
| 5 | Parses mixed basic + cloze | 2 Q/A + 1 cloze | 2 Basic, 1 Cloze |
| 6 | Multi-line answer | `Q: Q\nA: line1\nline2\nline3` | BasicCard with full back |
| 7 | Multi-line question | `Q: line1\nline2\nA: ans` | BasicCard with full front |
| 8 | Skips blockquotes | `> This is a note` block | 0 cards |
| 9 | Skips image-only blocks | `![[image.png]]` block | 0 cards |
| 10 | Cloze with multiple deletions | `{{c1::a}} and {{c2::b}}` | 1 ClozeCard with full text |
| 11 | Returns empty for empty section | `## Flashcards\n\n## Next` | 0 cards |
| 12 | Handles card with empty Q | `Q: \nA: answer` | 0 cards (skipped) |
| 13 | Handles card with empty A | `Q: question\nA: ` | 0 cards (skipped) |
| 14 | Preserves inline markdown | `Q: What is **bold**?\nA: It's _italic_` | Content preserved |

### 1.6 `parse_note()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Full pipeline with basic cards | File on disk | Complete `ParsedNote` |
| 2 | File not found | Non-existent path | Raises `FileNotFoundError` |
| 3 | Empty file | Empty `.md` file | ParsedNote with 0 cards |
| 4 | UTF-8 content (accents, CJK) | File with special chars | Correctly parsed cards |
| 5 | Accepts both `str` and `Path` | String path and Path object | Same result |

---

## 2. `test_images.py` — Image Detection & Handling

### 2.1 `extract_from_text()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Obsidian wiki-link | `![[photo.png]]` | `["photo.png"]` |
| 2 | Obsidian with subfolder | `![[assets/photo.png]]` | `["assets/photo.png"]` |
| 3 | Standard markdown | `![alt](img/photo.jpg)` | `["img/photo.jpg"]` |
| 4 | Multiple images in one string | Mix of both syntaxes | All refs extracted |
| 5 | No images | `Just plain text` | `[]` |
| 6 | All supported extensions | `.png .jpg .jpeg .gif .bmp .svg .webp` | All matched |
| 7 | Case-insensitive extension | `![[Photo.PNG]]` | Matched |
| 8 | Non-image wiki-link ignored | `![[document.pdf]]` | `[]` |
| 9 | Image in cloze syntax | `{{c1::![[img.png]]}}` | `["img.png"]` |

### 2.2 `resolve_path()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Resolves relative to note directory | Image in same dir as `.md` | Correct absolute path |
| 2 | Resolves relative to vault root | Image in `vault/images/` | Correct absolute path |
| 3 | Resolves via vault-wide search | Image in nested subfolder | Found by filename |
| 4 | Returns None when not found | Non-existent image | `None` |
| 5 | Skips hidden dirs during search | Image in `.hidden/` folder | `None` (not found) |
| 6 | Prefers note-relative over vault-relative | Image exists in both locations | Returns note-relative one |

### 2.3 `to_anki_syntax()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Obsidian → Anki | `![[photo.png]]` | `<img src="photo.png">` |
| 2 | Obsidian with path (strips dir) | `![[sub/photo.png]]` | `<img src="photo.png">` |
| 3 | Markdown → Anki | `![alt](dir/img.jpg)` | `<img src="img.jpg">` |
| 4 | Multiple images replaced | Text with 3 images | All converted |
| 5 | Non-image text preserved | `No images here` | Unchanged |
| 6 | Mixed images and text | `Text ![[a.png]] more ![b](c.jpg) end` | Both converted |

### 2.4 `copy_to_anki()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Copies image to media folder | Valid image ref + temp dirs | File exists in dest |
| 2 | Skips when already in dest | `dest == source` (same resolved path) | Not copied, skip logged |
| 3 | Dry run doesn't copy | `dry_run=True` | File NOT in dest |
| 4 | Empty image set | `set()` | No-op, skip message |
| 5 | Unresolvable image | Non-existent ref | `not_found` incremented |
| 6 | Multiple images mixed | 1 valid + 1 missing | 1 copied, 1 not found |

---

## 3. `test_exporter.py` — TSV Export

### 3.1 `_to_single_line()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Converts newlines | `"line1\nline2"` | `"line1<br>line2"` |
| 2 | No newlines unchanged | `"single line"` | `"single line"` |
| 3 | Multiple newlines | `"a\n\nb"` | `"a<br><br>b"` |

### 3.2 `_collect_images()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Collects from basic cards | Cards with images | Set of unique refs |
| 2 | Collects from cloze cards | Cloze with images | Set of unique refs |
| 3 | Deduplicates across cards | Same image in 2 cards | 1 entry in set |
| 4 | No images | Plain text cards | Empty set |

### 3.3 `_write_basic_file()`

| # | Test | Input | Expected file contents |
|---|------|-------|-----------------------|
| 1 | Single card, no tags | 1 BasicCard, tags="" | `front\tback\n` |
| 2 | Single card with tags | 1 BasicCard, tags="bio" | `front\tback\tbio\n` |
| 3 | Multiple cards | 3 BasicCards | 3 lines |
| 4 | Card with images | BasicCard with `![[img.png]]` | `<img src="img.png">` in output |
| 5 | Card with newlines | Multi-line front/back | `<br>` in output |
| 6 | Dry run | `dry_run=True` | File NOT created |
| 7 | UTF-8 characters | Cards with accents/CJK | Correct encoding |

### 3.4 `_write_cloze_file()`

| # | Test | Input | Expected file contents |
|---|------|-------|-----------------------|
| 1 | Single cloze, no tags | 1 ClozeCard | `text\n` |
| 2 | Single cloze with tags | 1 ClozeCard, tags="chem" | `text\tchem\n` |
| 3 | Multiple cloze cards | 3 ClozeCards | 3 lines |
| 4 | Dry run | `dry_run=True` | File NOT created |

### 3.5 `export()` — Full Pipeline

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Basic-only note | ParsedNote with 3 basic | `{stem} - Basic.txt` created, returns [path] |
| 2 | Cloze-only note | ParsedNote with 2 cloze | `{stem} - Cloze.txt` created, returns [path] |
| 3 | Mixed note | Both card types | Both files created, returns [path, path] |
| 4 | No cards | Empty ParsedNote | Returns `[]`, no files |
| 5 | Dry run | Any note with dry_run=True | Returns `[]`, no files on disk |
| 6 | on_step callback called | `on_step` mock | Called with correct (step, status, detail) |
| 7 | on_step receives "skip" for absent types | Basic-only note | on_step("Generate Cloze.txt", "skip", "") |
| 8 | Image copy error propagated | Bad media path | on_step("Copy images", "error", ...) |

---

## 4. `test_ankiconnect.py` — AnkiConnect Client

> All tests mock `urllib.request.urlopen` — no real Anki needed.

### 4.1 `_invoke()` (internal)

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Successful response | `{"result": 6, "error": null}` | Returns `6` |
| 2 | Error response | `{"result": null, "error": "msg"}` | Raises `AnkiConnectError` |
| 3 | Connection refused | `URLError` raised | Raises `AnkiConnectError` with descriptive msg |
| 4 | Timeout | `socket.timeout` | Raises `AnkiConnectError` |
| 5 | Sends correct JSON payload | Any action | Verify request body structure |
| 6 | Includes version 6 | Any action | `payload["version"] == 6` |

### 4.2 Connection checks

| # | Test | Expected |
|---|------|----------|
| 1 | `ping()` returns True on success | Mock version response → `True` |
| 2 | `ping()` returns False on error | Mock connection error → `False` |
| 3 | `version()` returns int | Mock response `6` → `6` |

### 4.3 Deck & Model info

| # | Test | Expected |
|---|------|----------|
| 1 | `deck_names()` | Returns list of deck name strings |
| 2 | `model_names()` | Returns list of model name strings |
| 3 | `model_field_names("Basic")` | Returns `["Front", "Back"]` |

### 4.4 Note CRUD

| # | Test | Expected |
|---|------|----------|
| 1 | `add_note()` success | Returns int note ID |
| 2 | `add_note()` returns null → error | Raises `AnkiConnectError` |
| 3 | `add_note()` includes allowDuplicate | Verify payload structure |
| 4 | `update_note()` calls updateNoteFields | Verify action sent |
| 5 | `update_note()` with tags calls clearUnusedTags | Verify both calls |
| 6 | `find_notes()` returns list of IDs | `[123, 456]` |
| 7 | `notes_info()` returns `AnkiNoteInfo` list | Correct dataclass fields |
| 8 | `notes_info()` skips empty/invalid items | Mixed response → only valid items |
| 9 | `notes_info()` with empty list | Returns `[]` without API call |
| 10 | `delete_notes()` sends note IDs | Verify payload |
| 11 | `delete_notes()` with empty list | No API call |
| 12 | `add_tags()` sends correct params | Verify `notes` and `tags` keys |
| 13 | `remove_tags()` sends correct params | Verify payload |

### 4.5 Media

| # | Test | Expected |
|---|------|----------|
| 1 | `get_media_dir_path()` success | Returns path string |
| 2 | `get_media_dir_path()` error | Returns `None` (no raise) |
| 3 | `store_media_file()` sends filename+path | Verify payload |

---

## 5. `test_sync.py` — Sync Engine

### 5.1 `parse_cards_with_ids()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Cards without IDs | Standard flashcards section | List of (card, None) tuples |
| 2 | Cards with IDs | Cards preceded by `<!-- anki-id: 123 -->` | List of (card, 123) tuples |
| 3 | Mixed: some with, some without IDs | Mixed content | Correct ID assignment per card |
| 4 | No flashcards section | Note without `## Flashcards` | `[]` |
| 5 | Skips blockquotes | `> quote` between cards | Not included in results |
| 6 | Skips image-only blocks | `![[img.png]]` block | Not included |
| 7 | ID before a cloze card | `<!-- anki-id: 99 -->\n{{c1::word}}` | `(ClozeCard, 99)` |

### 5.2 `_card_to_fields()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | BasicCard fields | BasicCard("Q", "A") | `{"Front": "Q", "Back": "A"}` |
| 2 | ClozeCard fields | ClozeCard("{{c1::w}}") | `{"Text": "{{c1::w}}"}` |
| 3 | Image conversion | BasicCard with `![[img.png]]`) | `<img src="img.png">` in value |
| 4 | Newline conversion | Multi-line card | `<br>` in field values |

### 5.3 `_fields_match()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Matching basic card | Card matches AnkiNoteInfo fields | `True` |
| 2 | Non-matching basic card | Front differs | `False` |
| 3 | Matching cloze card | Text field matches | `True` |
| 4 | Missing field in Anki | Anki has no "Front" key | `False` |

### 5.4 `_source_tag()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Simple filename | `Path("Biology.md")` | `"obsidian-src::biology"` |
| 2 | Filename with spaces | `Path("Organic Chemistry.md")` | `"obsidian-src::organic-chemistry"` |

### 5.5 `_to_local_path()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Non-Windows path unchanged | `/home/user/file` | Same string |
| 2 | Empty string | `""` | `""` |
| 3 | Windows path on Linux/WSL | `C:\Users\path` (mock wslpath) | Converted WSL path |
| 4 | Windows path when wslpath missing | `C:\Users\path` (FileNotFoundError) | Original path returned |

### 5.6 `write_ids_to_markdown()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Inserts new IDs | File without IDs + id_map | `<!-- anki-id: N -->` before each card block |
| 2 | Updates existing IDs | File with old IDs + new id_map | Old IDs replaced |
| 3 | Mixed new and existing | Some cards have IDs, some don't | Correct insertion/update |
| 4 | Preserves non-flashcard content | Frontmatter + other sections | Only flashcard section modified |
| 5 | No flashcards section | No `## Flashcards` | File unchanged |
| 6 | UTF-8 preserved | File with special chars | No encoding corruption |

### 5.7 `sync_note()` — Core Sync Pipeline

| # | Test | Mock Setup | Expected |
|---|------|-----------|----------|
| 1 | All new cards | `notes_info` returns empty, `add_note` returns IDs | `new_count == N`, IDs written to file |
| 2 | All unchanged cards | Cards match Anki fields | `unchanged_count == N`, no updates |
| 3 | Updated cards | Card content differs from Anki | `updated_count == N`, `update_note` called |
| 4 | Card deleted from Anki | ID exists in markdown but not in Anki | `deleted_from_anki += 1`, `add_note` called (re-create) |
| 5 | Orphan detection (no delete) | Anki has extra cards with src tag | `deleted_from_obsidian += N`, `add_tags("obsidian-orphan")` called |
| 6 | Orphan deletion | `delete_orphans=True` | `delete_notes()` called with orphan IDs |
| 7 | Dry run — new cards | `dry_run=True` | `new_count > 0` but `add_note` NOT called |
| 8 | Dry run — no file writes | `dry_run=True` | File content unchanged |
| 9 | Empty note (no cards) | ParsedNote with 0 cards | All step callbacks receive "skip" |
| 10 | AnkiConnect error on notes_info | `notes_info` raises error | `errors` list populated, early return |
| 11 | AnkiConnect error on add_note | `add_note` raises error | `error_count += 1`, continues with next card |
| 12 | on_step callbacks | `on_step` mock | All steps reported: Parse, Connect, Analyze, Sync, Write IDs |
| 13 | Image copy triggered | Cards with images | `copy_to_anki()` called |
| 14 | Image copy skipped in dry run | `dry_run=True` + images | `copy_to_anki()` NOT called |

---

## 6. `test_config.py` — Configuration Management

### 6.1 `load()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Loads existing config | `config.json` with data | Returns dict |
| 2 | Returns empty dict when missing | No `config.json` | `{}` |
| 3 | Handles valid JSON | `{"key": "value"}` | `{"key": "value"}` |

### 6.2 `save()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Writes JSON to file | `{"anki_media_path": "/tmp"}` | File contains valid JSON |
| 2 | Overwrites existing | Save twice with different data | Second data persists |
| 3 | Handles UTF-8 | Dict with unicode values | Correct encoding |

### 6.3 `get_anki_media_path()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | CLI override takes priority | `cli_override="/new/path"` | Returns `/new/path`, saved to config |
| 2 | Returns saved path | Config has `anki_media_path` | Returns saved path |
| 3 | Interactive prompt (mock input) | No CLI, no saved config | Prompts user, saves result |
| 4 | Creates directory if missing | Non-existent path entered | `os.makedirs` called |

### 6.4 `get_ankiconnect_url()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | CLI override | `cli_override="http://custom:1234"` | Returns custom URL, saved |
| 2 | Returns saved URL | Config has `ankiconnect_url` | Returns saved URL |
| 3 | Returns default | No CLI, no saved | `"http://127.0.0.1:8765"` |

### 6.5 `discover_md_files()`

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | Finds `.md` files in flat dir | Folder with 3 `.md` files | 3 files |
| 2 | Non-recursive ignores subfolders | Folder with nested `.md` | Only top-level files |
| 3 | Recursive finds nested files | `recursive=True` | All nested `.md` files |
| 4 | Skips `.obsidian` folder | `.obsidian/` has `.md` files | Not included |
| 5 | Skips `.trash` folder | `.trash/` has `.md` files | Not included |
| 6 | Skips `.git` folder | `.git/` has files | Not included |
| 7 | Skips `Scripts` folder | `Scripts/` has `.md` files | Not included |
| 8 | Skips `Templates` folder | `Templates/` has `.md` files | Not included |
| 9 | Returns sorted list | Files in random order | Alphabetically sorted |
| 10 | Empty folder | No `.md` files | `[]` |

---

## 7. `test_main_cli.py` — CLI Entry Point

> Uses `monkeypatch` / `mock.patch` to avoid real file I/O and real AnkiConnect.

### 7.1 Argument parsing

| # | Test | Args | Expected |
|---|------|------|----------|
| 1 | Single file export | `["note.md"]` | `run_single()` called |
| 2 | Folder batch export | `["./folder"]` | `run_batch()` called |
| 3 | Recursive flag | `["./folder", "-r"]` | `run_batch(recursive=True)` |
| 4 | Dry run flag | `["note.md", "--dry-run"]` | `dry_run=True` |
| 5 | Sync mode single | `["note.md", "--sync"]` | `run_sync_single()` called |
| 6 | Sync mode batch | `["./folder", "--sync"]` | `run_sync_batch()` called |
| 7 | Custom AnkiConnect URL | `["note.md", "--sync", "--ankiconnect-url", "http://x:1"]` | URL passed through |
| 8 | Delete orphans | `[".", "--sync", "--delete-orphans"]` | `delete_orphans=True` |
| 9 | --version | `["--version"]` | Prints version, exits |
| 10 | Invalid path | `["nonexistent"]` | `sys.exit(1)` |
| 11 | --gui flag | `["--gui"]` | `gui.main()` called |

### 7.2 `run_single()`

| # | Test | Expected |
|---|------|----------|
| 1 | Calls parse_note then export | Both functions invoked in order |
| 2 | FileNotFoundError → sys.exit(1) | Exits cleanly |

### 7.3 `run_batch()`

| # | Test | Expected |
|---|------|----------|
| 1 | Processes all discovered files | parse_note + export called per file |
| 2 | Continues on error | 1 bad file doesn't stop batch |
| 3 | No files found | Prints message, returns |

### 7.4 `run_sync_single()`

| # | Test | Expected |
|---|------|----------|
| 1 | Pings then syncs | `client.ping()` then `sync_note()` |
| 2 | Ping fails → sys.exit(1) | Exits if AnkiConnect unreachable |

### 7.5 `run_sync_batch()`

| # | Test | Expected |
|---|------|----------|
| 1 | Syncs all discovered files | `sync_note()` called per file |
| 2 | Ping fails → sys.exit(1) | Exits early |
| 3 | Accumulates totals | `total_new`, `total_updated` correct |

---

## 8. `test_integration.py` — End-to-End (No Anki Required)

These tests wire together real modules (parser, images, exporter) with temp files on disk, but mock AnkiConnect for sync tests.

| # | Test | Description |
|---|------|-------------|
| 1 | **Export round-trip** | Create `.md` file → `parse_note()` → `export()` → verify TSV content matches cards |
| 2 | **Export with images** | `.md` with image refs + real image files → export → verify images copied + Anki syntax in TSV |
| 3 | **Sync round-trip** | `.md` file → `parse_note()` → `sync_note()` (mocked client) → verify IDs written back to `.md` |
| 4 | **Sync then re-sync** | Sync once (IDs written) → modify card content → sync again → verify UPDATE called |
| 5 | **Sync idempotent** | Sync → sync again (no changes) → verify all UNCHANGED |
| 6 | **Batch export** | Folder with 3 `.md` files → `run_batch()` → 3 sets of output files |
| 7 | **Recursive discovery + export** | Nested folder structure → recursive → all notes exported |
| 8 | **Dry run produces no artifacts** | `--dry-run` → no `.txt` files, no copied images, no markdown modifications |
| 9 | **Note with no cards** | `.md` without `## Flashcards` → export returns `[]`, sync returns empty result |
| 10 | **Orphan detection** | Sync note → remove a card → re-sync → verify orphan tagged/deleted |

---

## Testing Strategy Notes

### What we mock
- **`urllib.request.urlopen`** — All AnkiConnect HTTP calls (no real Anki needed)
- **`input()`** — Interactive config prompts
- **`config.CONFIG_FILE`** — Point to temp file so tests don't touch real config
- **`shutil.copy2`** — Optionally, to verify copy calls without real I/O (integration tests use real copies)
- **`subprocess.check_output`** — WSL path conversion in `_to_local_path`

### What we DON'T mock (test for real)
- File reads/writes (using `tmp_path` fixture)
- Regex parsing (parser, images)
- TSV generation (exporter)
- Markdown ID insertion (sync)
- Path resolution logic (images)

### What we skip
- **GUI (`gui.py`)** — Requires PySide6 event loop, QThread. Can't be reliably unit tested without a display server. Manual testing or screenshot testing recommended.
- **Real AnkiConnect** — Optional integration test that requires Anki running (marked `@pytest.mark.slow` or `@pytest.mark.requires_anki`)

### Coverage targets
| Module | Target |
|--------|--------|
| `parser.py` | 100% |
| `images.py` | 100% |
| `exporter.py` | 100% |
| `ankiconnect.py` | 100% |
| `sync.py` | 95%+ (WSL branch depends on platform) |
| `config.py` | 95%+ (interactive prompt branch) |
| `__main__.py` | 90%+ |
| **Overall** | **95%+** |

### Running

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=obsidian_to_anki --cov-report=term-missing

# Run a specific module
pytest tests/test_parser.py -v

# Run only fast tests (exclude integration)
pytest tests/ -v -m "not slow"
```

### Estimated test count: ~120 tests
