# Test Coverage Audit

**Baseline:** 218 tests, all passing (0.88s)
**Date:** 2026-02-27

---

## 1. Gap Analysis by Source File

### parser.py — Well covered (38 tests)

| Function | Tests | Status |
|---|---|---|
| `find_vault_root()` | 4 | ✅ Complete |
| `extract_tags()` | 8 | ✅ Complete |
| `extract_deck_name()` | 6 | ✅ Complete |
| `_extract_flashcards_section()` | 4 | ✅ Complete |
| `_split_into_blocks()` | 3 | ✅ Complete |
| `_parse_qa_block()` | 4 | ✅ Complete |
| `parse_flashcards()` | 8 | ✅ Complete |
| `parse_note()` | 5 | ✅ Complete |

**Missing:**
- No test for blocks that don't match Q: or cloze pattern (silently ignored)
- No test for `parse_note()` with encoding errors (non-UTF-8 file)
- No test for frontmatter with extra YAML fields (robustness)

### exporter.py — Mostly covered (26 tests), some gaps

| Function | Tests | Status |
|---|---|---|
| `_to_single_line()` | 3 | ✅ Complete |
| `_collect_images()` | 4 | ✅ Complete |
| `_write_basic_file()` | 7 | ✅ Complete |
| `_write_cloze_file()` | 4 | ⚠️ Missing parity with basic |
| `_print_import_instructions()` | 0 | ⚠️ Untested (low priority, print-only) |
| `export()` | 8 | ⚠️ Missing error branch tests |

**Missing:**
- `_write_cloze_file`: No tests for newline conversion, image conversion, or multiple cards (all tested for `_write_basic_file` but not cloze)
- `export()`: No test for exception during image copy step (line 162 catch branch)
- `export()`: No test for exception during Basic.txt generation (line 183 catch branch)
- `export()`: No test for exception during Cloze.txt generation (line 205 catch branch)
- `_escape_tsv` is listed in test imports but doesn't exist in source — dead import

### images.py — Well covered (27 tests)

| Function | Tests | Status |
|---|---|---|
| `extract_from_text()` | 9 | ✅ Complete |
| `resolve_path()` | 6 | ✅ Complete |
| `to_anki_syntax()` | 6 | ✅ Complete |
| `copy_to_anki()` | 6 | ✅ Complete |

**Missing:**
- `resolve_path`: No test for image reference with spaces in filename
- `copy_to_anki`: No test for `shutil.copy2` failure (permission denied, disk full)
- `copy_to_anki`: No test for dry-run counting (verifying printed output stats)

### config.py — Well covered (23 tests)

| Function | Tests | Status |
|---|---|---|
| `load()` | 3 | ⚠️ Missing malformed JSON test |
| `save()` | 3 | ✅ Complete |
| `get_anki_media_path()` | 4 | ✅ Complete |
| `get_ankiconnect_url()` | 3 | ✅ Complete |
| `discover_md_files()` | 10 | ✅ Complete |

**Missing:**
- `load()`: No test for corrupted/malformed JSON file (JSONDecodeError)
- `get_anki_media_path()`: No test for input with surrounding quotes being stripped (line 66)
- `get_ankiconnect_url()`: No test for cli_override saving to config (verified reload)

### ankiconnect.py — Well covered (28 tests), one untested method

| Function | Tests | Status |
|---|---|---|
| `_invoke()` | 6 | ✅ Complete |
| `ping()` | 2 | ✅ Complete |
| `version()` | 1 | ✅ Complete |
| `deck_names()` | 1 | ✅ Complete |
| `model_names()` | 1 | ✅ Complete |
| `model_field_names()` | 1 | ✅ Complete |
| `add_note()` | 3 | ✅ Complete |
| `update_note()` | 2 | ✅ Complete |
| `add_tags()` | 1 | ✅ Complete |
| `remove_tags()` | 1 | ✅ Complete |
| `find_notes()` | 1 | ✅ Complete |
| `notes_info()` | 3 | ✅ Complete |
| `delete_notes()` | 2 | ✅ Complete |
| `get_media_dir_path()` | 2 | ✅ Complete |
| `store_media_file()` | 1 | ✅ Complete |
| `export_package()` | 0 | ❌ Not tested |

**Missing:**
- `export_package()` — completely untested
- `_invoke()` with `OSError` (in the except clause but never tested separately)
- `notes_info()` with item missing "noteId" key (vs null item)
- `update_note()` error during `clearUnusedTags` second call
- `AnkiConnectClient.__init__()` — no test verifying custom timeout is stored

### sync.py — Mostly covered (46 tests), missing critical error paths

| Function | Tests | Status |
|---|---|---|
| `parse_cards_with_ids()` | 7 | ✅ Complete |
| `_parse_qa_block()` | 0 | ⚠️ Internal duplicate, untested |
| `_card_to_fields()` | 4 | ✅ Complete |
| `_fields_match()` | 4 | ✅ Complete |
| `_card_summary()` | 3 | ✅ Complete |
| `_card_type()` | 1 | ✅ Complete |
| `_model_name()` | 1 | ✅ Complete |
| `_source_tag()` | 3 | ✅ Complete |
| `_to_local_path()` | 4 | ⚠️ Missing WSL mock test |
| `write_ids_to_markdown()` | 7 | ⚠️ Missing mixed-card test |
| `sync_note()` | 11 | ⚠️ Missing error path tests |

**Missing (HIGH PRIORITY — these are the riskiest code paths):**
- `sync_note()`: No test for `AnkiConnectError` during `update_note` (line 333 catch)
- `sync_note()`: No test for `AnkiConnectError` during `add_note` for new cards (line 391 catch)
- `sync_note()`: No test for `AnkiConnectError` during `add_note` for re-created cards (line 370 catch)
- `sync_note()`: No test for `AnkiConnectError` during orphan detection `find_notes` (line 444 catch)
- `sync_note()`: No test for `Exception` during `write_ids_to_markdown` (line 462 catch)
- `sync_note()`: No test for image copying step (step 6, lines 471-498)
- `sync_note()`: No test for image copy when media path comes from config fallback
- `_to_local_path()`: No test with mocked `wslpath` subprocess succeeding
- `_to_local_path()`: No test for `FileNotFoundError` from subprocess (wslpath not found)
- `write_ids_to_markdown()`: No test for mixed basic + cloze cards together
- `write_ids_to_markdown()`: No test for cards with existing IDs being updated alongside new cards

### __main__.py — Adequately covered (18 tests), minor gaps

| Function | Tests | Status |
|---|---|---|
| `_print_banner()` | 0 | Low priority (print-only) |
| `_print_sync_banner()` | 0 | Low priority (print-only) |
| `_print_summary()` | 0 | Low priority (print-only) |
| `_print_sync_summary()` | 0 | Low priority (print-only) |
| `run_single()` | 2 | ✅ Complete |
| `run_batch()` | 3 | ✅ Complete |
| `run_sync_single()` | 2 | ✅ Complete |
| `run_sync_batch()` | 2 | ⚠️ Missing error continuation test |
| `main()` | 9 | ⚠️ Missing --gui and --version tests |

**Missing:**
- `main()`: No test for `--gui` flag dispatching to gui_main
- `main()`: No test for `--version` flag
- `main()`: No test for `--ankiconnect-url` override
- `run_sync_batch()`: No test for continues-on-error (one file fails, next still processes)
- `run_sync_batch()`: No test for ping failure exits

### gui.py — ❌ ZERO tests (largest file, 1100+ lines)

| Class | Tests | Status |
|---|---|---|
| `StdoutRedirector` | 0 | ❌ Testable without Qt app |
| `ConvertWorker` | 0 | ❌ Logic testable with mocks |
| `SyncWorker` | 0 | ❌ Logic testable with mocks |
| `MainWindow` | 0 | ❌ Requires Qt app (lower priority) |

**Testable without a running Qt display:**
- `StdoutRedirector`: write/flush behavior, signal emission
- `ConvertWorker._run_single()` and `._run_batch()`: logic with mocked signals
- `SyncWorker._run_single()` and `._run_batch()`: logic with mocked signals
- `MainWindow._on_mode_changed()`, `_reset_ui_state()`, `_show_validation_error()` — with headless QApplication

### test_integration.py — Good but missing some scenarios (10 tests)

**Missing:**
- No integration test for sync with image copying (images + sync flow combined)
- No integration test for sync with update + orphan deletion in a single run
- No integration test for batch sync (multiple files, one AnkiConnect client)
- No integration test for re-syncing a previously synced file (IDs already present)

---

## 2. Implementation Plan

### Priority 1: sync.py error paths (CRITICAL — 11 new tests)
**Why:** sync.py modifies both Anki and local markdown files. Untested error branches could silently lose data or leave files in an inconsistent state.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 1 | `test_update_error_records_and_continues` | `sync_note()` | `update_note` raises `AnkiConnectError` | Card update silently fails, no error reported |
| 2 | `test_add_new_card_error_records` | `sync_note()` | `add_note` raises for a new card | New card lost, no error trail |
| 3 | `test_recreate_error_records` | `sync_note()` | `add_note` raises when re-creating deleted card | Card permanently lost after Anki deletion |
| 4 | `test_orphan_detection_error_continues` | `sync_note()` | `find_notes` raises `AnkiConnectError` | Orphans silently accumulate |
| 5 | `test_write_ids_failure_records_error` | `sync_note()` | `write_ids_to_markdown` raises | IDs not written, next sync re-creates duplicates |
| 6 | `test_image_copy_with_media_from_client` | `sync_note()` | `get_media_dir_path` returns valid path | Images never copied to Anki |
| 7 | `test_image_copy_falls_back_to_config` | `sync_note()` | `get_media_dir_path` returns None, config has path | Images lost when AnkiConnect lacks media API |
| 8 | `test_image_copy_no_media_path_warns` | `sync_note()` | No media path available anywhere | Silent failure, images missing from cards |
| 9 | `test_wslpath_conversion_success` | `_to_local_path()` | Mock wslpath returning converted path | Windows path not converted under WSL |
| 10 | `test_wslpath_not_found_returns_original` | `_to_local_path()` | `subprocess` raises `FileNotFoundError` | Crash when wslpath not available |
| 11 | `test_write_ids_mixed_basic_and_cloze` | `write_ids_to_markdown()` | File with both card types | IDs written to wrong cards |

### Priority 2: exporter.py gap fill (7 new tests)
**Why:** Cloze file generation has less test parity than Basic. Export error branches could silently fail in batch operations.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 12 | `test_cloze_newlines_converted` | `_write_cloze_file()` | Cloze text with newlines | Broken card formatting in Anki |
| 13 | `test_cloze_image_conversion` | `_write_cloze_file()` | Cloze text with image reference | Image not displayed |
| 14 | `test_cloze_multiple_cards` | `_write_cloze_file()` | Multiple cloze cards | Only first card written |
| 15 | `test_export_image_copy_exception` | `export()` | Image copy raises exception | Export crashes instead of continuing |
| 16 | `test_export_basic_write_exception` | `export()` | Basic file write raises exception | Export crashes, no cloze file generated |
| 17 | `test_export_cloze_write_exception` | `export()` | Cloze file write raises exception | Partial output, no error signal |
| 18 | `test_export_on_step_error_callbacks` | `export()` | Error callbacks fire with correct status | GUI shows wrong step status |

### Priority 3: ankiconnect.py missing method (3 new tests)
**Why:** `export_package()` is used by the GUI backup feature. Completely untested.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 19 | `test_export_package_success` | `export_package()` | Returns True | Backup silently fails |
| 20 | `test_export_package_sends_params` | `export_package()` | Correct deck/path/includeSched sent | Wrong deck backed up |
| 21 | `test_invoke_os_error` | `_invoke()` | `OSError` from urlopen | Unhandled crash |

### Priority 4: config.py edge cases (3 new tests)
**Why:** Corrupted config files are a common real-world issue.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 22 | `test_load_malformed_json` | `load()` | Config file contains invalid JSON | Crash on startup |
| 23 | `test_media_path_strips_quotes` | `get_anki_media_path()` | User pastes path with surrounding quotes | Path not found |
| 24 | `test_ankiconnect_url_cli_override_saved` | `get_ankiconnect_url()` | CLI override persists to config | URL not remembered |

### Priority 5: __main__.py completeness (5 new tests)
**Why:** CLI is the primary interface. Missing flag tests could mask regressions.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 25 | `test_gui_flag_launches_gui` | `main()` | `--gui` in sys.argv | GUI never launches from CLI |
| 26 | `test_version_flag` | `main()` | `--version` in sys.argv | Version display broken |
| 27 | `test_ankiconnect_url_override` | `main()` | `--ankiconnect-url` with `--sync` | Custom URL ignored |
| 28 | `test_sync_batch_continues_on_error` | `run_sync_batch()` | One file fails, next continues | Batch aborts on first error |
| 29 | `test_sync_batch_ping_failure` | `run_sync_batch()` | `client.ping()` returns False | Unclear error for user |

### Priority 6: Integration tests (5 new tests)
**Why:** End-to-end flows catch interaction bugs that unit tests miss.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 30 | `test_sync_with_images_integration` | sync + images | Sync copies images to Anki media | Images missing after sync |
| 31 | `test_resync_previously_synced_file` | sync round-trip | File already has anki-id comments | IDs corrupted or duplicated |
| 32 | `test_sync_update_and_orphan_same_run` | sync complex | One card updated, one orphaned | Orphan not detected when cards change |
| 33 | `test_batch_sync_multiple_files` | run_sync_batch | 3 files, one fails, others succeed | Batch count wrong |
| 34 | `test_export_then_re_export_overwrites` | export round-trip | Export twice to same folder | Old cards not replaced |

### Priority 7: gui.py worker threads (6 new tests, requires QApplication)
**Why:** Workers contain business logic that drives the GUI. Zero coverage is a risk for the most user-facing component. These tests need `QApplication` but NOT a display.

| # | Test | Target | Scenario | Risk |
|---|---|---|---|---|
| 35 | `test_stdout_redirector_emits_signal` | `StdoutRedirector` | write() emits text_written | Log output lost in GUI |
| 36 | `test_stdout_redirector_flush_noop` | `StdoutRedirector` | flush() doesn't crash | Crash during log output |
| 37 | `test_convert_worker_single_file` | `ConvertWorker` | Single file processing | Worker thread crashes |
| 38 | `test_convert_worker_batch` | `ConvertWorker` | Folder with multiple files | Batch progress wrong |
| 39 | `test_sync_worker_ping_failure` | `SyncWorker` | AnkiConnect unreachable | No error message shown |
| 40 | `test_sync_worker_backup_flow` | `SyncWorker` | Backup before sync | Backup silently fails |

---

## 3. Summary

| Category | Existing | Planned | Total |
|---|---|---|---|
| parser.py | 38 | 0 | 38 |
| exporter.py | 26 | 7 | 33 |
| images.py | 27 | 0 | 27 |
| config.py | 23 | 3 | 26 |
| ankiconnect.py | 28 | 3 | 31 |
| sync.py | 46 | 11 | 57 |
| __main__.py | 18 | 5 | 23 |
| gui.py | 0 | 6 | 6 |
| integration | 10 | 5 | 15 |
| **TOTAL** | **218** | **40** | **258** |

### Untestable / Excluded

- `_print_banner()`, `_print_sync_banner()`, `_print_summary()`, `_print_sync_summary()`, `_print_import_instructions()` — Pure print functions with no return values or side effects beyond stdout. Testing these adds noise without catching bugs.
- `MainWindow` widget layout/styling — Requires a live display. Individual methods like `_on_mode_changed()` could be tested with headless QApplication but provide low value relative to effort.
- `gui.py` WSL Wayland workaround (line 17-18) — Platform-specific, would need WSL environment detection mocks.
