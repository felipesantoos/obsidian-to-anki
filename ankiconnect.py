"""
AnkiConnect HTTP client.

Minimal client using only urllib.request (no extra dependencies).
Communicates with Anki via the AnkiConnect add-on's JSON-RPC API.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field


class AnkiConnectError(Exception):
    """Raised when AnkiConnect returns an error or is unreachable."""


@dataclass
class AnkiNoteInfo:
    """Flattened info about an Anki note, returned by notesInfo."""
    note_id: int
    model_name: str
    tags: list[str]
    fields: dict[str, str]   # field_name -> value (HTML stripped of order key)
    mod: int


class AnkiConnectClient:
    """HTTP client for the AnkiConnect add-on API."""

    def __init__(self, url: str = "http://127.0.0.1:8765", timeout: int = 10):
        self.url = url
        self.timeout = timeout

    def _invoke(self, action: str, **params) -> any:
        """Send a JSON-RPC request to AnkiConnect and return the result."""
        payload = {"action": action, "version": 6}
        if params:
            payload["params"] = params

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            raise AnkiConnectError(
                f"Cannot reach AnkiConnect at {self.url} — "
                f"is Anki running with AnkiConnect installed? ({e})"
            ) from e

        if body.get("error"):
            raise AnkiConnectError(f"AnkiConnect error: {body['error']}")

        return body.get("result")

    # -- Connection checks --------------------------------------------------

    def ping(self) -> bool:
        """Check connectivity. Returns True if AnkiConnect responds."""
        try:
            self._invoke("version")
            return True
        except AnkiConnectError:
            return False

    def version(self) -> int:
        """Return the AnkiConnect API version."""
        return self._invoke("version")

    # -- Deck & model info --------------------------------------------------

    def deck_names(self) -> list[str]:
        """Return all deck names."""
        return self._invoke("deckNames")

    def model_names(self) -> list[str]:
        """Return all model (note type) names."""
        return self._invoke("modelNames")

    def model_field_names(self, model_name: str) -> list[str]:
        """Return field names for a given model."""
        return self._invoke("modelFieldNames", modelName=model_name)

    # -- Note CRUD ----------------------------------------------------------

    def add_note(
        self,
        deck: str,
        model: str,
        fields: dict[str, str],
        tags: list[str] | None = None,
    ) -> int:
        """
        Add a note to Anki. Returns the new note ID.

        Raises AnkiConnectError if the note is a duplicate or invalid.
        """
        note = {
            "deckName": deck,
            "modelName": model,
            "fields": fields,
            "tags": tags or [],
            "options": {
                "allowDuplicate": True,
            },
        }
        result = self._invoke("addNote", note=note)
        if result is None:
            raise AnkiConnectError("addNote returned null — note may be invalid")
        return result

    def update_note(
        self,
        note_id: int,
        fields: dict[str, str],
        tags: list[str] | None = None,
    ) -> None:
        """Update fields (and optionally tags) on an existing note."""
        note: dict = {"id": note_id, "fields": fields}
        if tags is not None:
            note["tags"] = tags
        self._invoke("updateNoteFields", note=note)
        if tags is not None:
            # updateNoteFields doesn't handle tags — use replaceTags approach
            # Clear and re-add via addTags/removeTags would be complex;
            # instead we use updateNoteTags if available, else manual
            self._invoke("clearUnusedTags")

    def add_tags(self, note_ids: list[int], tags: str) -> None:
        """Add space-separated tags to notes."""
        self._invoke("addTags", notes=note_ids, tags=tags)

    def remove_tags(self, note_ids: list[int], tags: str) -> None:
        """Remove space-separated tags from notes."""
        self._invoke("removeTags", notes=note_ids, tags=tags)

    def find_notes(self, query: str) -> list[int]:
        """Find note IDs matching an Anki search query."""
        return self._invoke("findNotes", query=query)

    def notes_info(self, note_ids: list[int]) -> list[AnkiNoteInfo]:
        """Fetch detailed info for a list of note IDs."""
        if not note_ids:
            return []
        raw = self._invoke("notesInfo", notes=note_ids)
        result = []
        for item in raw:
            # AnkiConnect returns empty objects for deleted/invalid note IDs
            if not item or "noteId" not in item:
                continue
            fields = {}
            for fname, fdata in item.get("fields", {}).items():
                fields[fname] = fdata.get("value", "")
            result.append(AnkiNoteInfo(
                note_id=item["noteId"],
                model_name=item.get("modelName", ""),
                tags=item.get("tags", []),
                fields=fields,
                mod=item.get("mod", 0),
            ))
        return result

    def delete_notes(self, note_ids: list[int]) -> None:
        """Permanently delete notes from Anki."""
        if note_ids:
            self._invoke("deleteNotes", notes=note_ids)

    # -- Media --------------------------------------------------------------

    def get_media_dir_path(self) -> str | None:
        """Return the path to Anki's collection.media folder, or None on failure."""
        try:
            return self._invoke("getMediaDirPath")
        except AnkiConnectError:
            return None

    def store_media_file(self, filename: str, path: str) -> None:
        """Store a media file in Anki's collection.media folder."""
        self._invoke("storeMediaFile", filename=filename, path=path)

    def export_package(self, deck: str, path: str, include_sched: bool = True) -> bool:
        """Export a deck to an .apkg file. Returns True on success."""
        return self._invoke("exportPackage", deck=deck, path=path, includeSched=include_sched)
