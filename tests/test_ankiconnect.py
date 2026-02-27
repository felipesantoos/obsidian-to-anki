"""Tests for obsidian_to_anki.ankiconnect."""

import json
import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock

from obsidian_to_anki.ankiconnect import (
    AnkiConnectClient,
    AnkiConnectError,
    AnkiNoteInfo,
)


def _mock_response(result=None, error=None):
    """Create a mock urlopen response."""
    body = json.dumps({"result": result, "error": error}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture
def client():
    return AnkiConnectClient(url="http://localhost:9999", timeout=5)


# ── _invoke ──────────────────────────────────────────────────────────────

class TestInvoke:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=6)
        assert client._invoke("version") == 6

    @patch("urllib.request.urlopen")
    def test_sends_correct_payload(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result="ok")
        client._invoke("deckNames")

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        payload = json.loads(req.data)
        assert payload["action"] == "deckNames"
        assert payload["version"] == 6

    @patch("urllib.request.urlopen")
    def test_sends_params(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=999)
        client._invoke("addNote", note={"deck": "Test"})

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["params"]["note"]["deck"] == "Test"

    @patch("urllib.request.urlopen")
    def test_api_error_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(error="invalid action")
        with pytest.raises(AnkiConnectError, match="invalid action"):
            client._invoke("badAction")

    @patch("urllib.request.urlopen")
    def test_connection_error_raises(self, mock_urlopen, client):
        mock_urlopen.side_effect = ConnectionError("refused")
        with pytest.raises(AnkiConnectError, match="Cannot reach"):
            client._invoke("version")

    @patch("urllib.request.urlopen")
    def test_url_error_raises(self, mock_urlopen, client):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")
        with pytest.raises(AnkiConnectError, match="Cannot reach"):
            client._invoke("version")


# ── ping / version ───────────────────────────────────────────────────────

class TestConnectionChecks:
    @patch("urllib.request.urlopen")
    def test_ping_true(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=6)
        assert client.ping() is True

    @patch("urllib.request.urlopen")
    def test_ping_false_on_error(self, mock_urlopen, client):
        mock_urlopen.side_effect = ConnectionError("refused")
        assert client.ping() is False

    @patch("urllib.request.urlopen")
    def test_version(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=6)
        assert client.version() == 6


# ── deck & model info ────────────────────────────────────────────────────

class TestDeckModelInfo:
    @patch("urllib.request.urlopen")
    def test_deck_names(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=["Default", "Science"])
        assert client.deck_names() == ["Default", "Science"]

    @patch("urllib.request.urlopen")
    def test_model_names(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=["Basic", "Cloze"])
        assert client.model_names() == ["Basic", "Cloze"]

    @patch("urllib.request.urlopen")
    def test_model_field_names(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=["Front", "Back"])
        assert client.model_field_names("Basic") == ["Front", "Back"]


# ── Note CRUD ────────────────────────────────────────────────────────────

class TestNoteCRUD:
    @patch("urllib.request.urlopen")
    def test_add_note_returns_id(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=12345)
        nid = client.add_note("Default", "Basic", {"Front": "Q", "Back": "A"})
        assert nid == 12345

    @patch("urllib.request.urlopen")
    def test_add_note_null_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        with pytest.raises(AnkiConnectError, match="null"):
            client.add_note("Default", "Basic", {"Front": "Q", "Back": "A"})

    @patch("urllib.request.urlopen")
    def test_add_note_with_tags(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=99)
        client.add_note("Deck", "Basic", {"Front": "Q"}, tags=["tag1"])

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["params"]["note"]["tags"] == ["tag1"]

    @patch("urllib.request.urlopen")
    def test_update_note(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.update_note(123, {"Front": "new Q"})
        assert mock_urlopen.called

    @patch("urllib.request.urlopen")
    def test_update_note_with_tags(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.update_note(123, {"Front": "Q"}, tags=["t1"])
        # Should make 2 calls: updateNoteFields + clearUnusedTags
        assert mock_urlopen.call_count == 2

    @patch("urllib.request.urlopen")
    def test_find_notes(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=[1, 2, 3])
        assert client.find_notes("deck:Default") == [1, 2, 3]

    @patch("urllib.request.urlopen")
    def test_notes_info(self, mock_urlopen, client):
        raw = [
            {
                "noteId": 100,
                "modelName": "Basic",
                "tags": ["bio"],
                "fields": {"Front": {"value": "Q"}, "Back": {"value": "A"}},
                "mod": 1700000000,
            }
        ]
        mock_urlopen.return_value = _mock_response(result=raw)
        infos = client.notes_info([100])
        assert len(infos) == 1
        assert infos[0].note_id == 100
        assert infos[0].fields["Front"] == "Q"

    @patch("urllib.request.urlopen")
    def test_notes_info_empty_list(self, mock_urlopen, client):
        assert client.notes_info([]) == []
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_notes_info_skips_deleted(self, mock_urlopen, client):
        raw = [None, {"noteId": 1, "modelName": "Basic", "tags": [], "fields": {}, "mod": 0}]
        mock_urlopen.return_value = _mock_response(result=raw)
        infos = client.notes_info([999, 1])
        assert len(infos) == 1

    @patch("urllib.request.urlopen")
    def test_delete_notes(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.delete_notes([1, 2])
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["action"] == "deleteNotes"
        assert payload["params"]["notes"] == [1, 2]

    @patch("urllib.request.urlopen")
    def test_delete_notes_empty_noop(self, mock_urlopen, client):
        client.delete_notes([])
        mock_urlopen.assert_not_called()


# ── Tags ─────────────────────────────────────────────────────────────────

class TestTags:
    @patch("urllib.request.urlopen")
    def test_add_tags(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.add_tags([1, 2], "bio science")
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["params"]["tags"] == "bio science"

    @patch("urllib.request.urlopen")
    def test_remove_tags(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.remove_tags([1], "old-tag")
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["action"] == "removeTags"


# ── Media ────────────────────────────────────────────────────────────────

class TestMedia:
    @patch("urllib.request.urlopen")
    def test_get_media_dir_path(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result="/path/to/media")
        assert client.get_media_dir_path() == "/path/to/media"

    @patch("urllib.request.urlopen")
    def test_get_media_dir_path_error(self, mock_urlopen, client):
        mock_urlopen.side_effect = ConnectionError("no")
        assert client.get_media_dir_path() is None

    @patch("urllib.request.urlopen")
    def test_store_media_file(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=None)
        client.store_media_file("img.png", "/path/img.png")
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["params"]["filename"] == "img.png"


# ── export_package ──────────────────────────────────────────────────────

class TestExportPackage:
    @patch("urllib.request.urlopen")
    def test_export_package_success(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=True)
        assert client.export_package("Default", "/tmp/deck.apkg") is True

    @patch("urllib.request.urlopen")
    def test_export_package_sends_params(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(result=True)
        client.export_package("Science", "/backup/sci.apkg", include_sched=False)
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data)
        assert payload["action"] == "exportPackage"
        assert payload["params"]["deck"] == "Science"
        assert payload["params"]["path"] == "/backup/sci.apkg"
        assert payload["params"]["includeSched"] is False


# ── _invoke edge cases ─────────────────────────────────────────────────

class TestInvokeEdgeCases:
    @patch("urllib.request.urlopen")
    def test_os_error_raises(self, mock_urlopen, client):
        mock_urlopen.side_effect = OSError("network down")
        with pytest.raises(AnkiConnectError, match="Cannot reach"):
            client._invoke("version")
