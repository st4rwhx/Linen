"""Publishing runs against Roblox once and against a stand-in every other time.

The real endpoint cannot be in a test suite — it needs a key, it makes assets
that then exist, and it is rate limited. So these run a small HTTP server that
answers the shapes the Assets API documents, and check what Linen *sends*: the
two-field form, the header the key rides in, the operation poll, and the
handling when the answer is a refusal rather than an asset.

The one thing that cannot be checked against a stand-in is whether Roblox
accepts a `.rbxmx` this project generated. Roblox warns that files not written
by Studio may not process, so that stays an open question until one is uploaded
for real.
"""
from __future__ import annotations

import email.parser
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from linen.cloud import (
    Creator,
    PublishError,
    api_key,
    load_manifest,
    publish,
    save_manifest,
)

KEY = "secret-key-do-not-leak"


class _Api(BaseHTTPRequestHandler):
    """Enough of the Assets API to answer honestly, and to record what arrived."""

    seen: ClassVar[list[dict]] = []
    behaviour: ClassVar[str] = "operation"

    def log_message(self, *args) -> None:  # keep the test output clean
        pass

    def _record(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        call = {
            "path": self.path,
            "method": self.command,
            "key": self.headers.get("x-api-key"),
            "fields": {},
        }
        content_type = self.headers.get("Content-Type", "")
        if raw and content_type.startswith("multipart/"):
            message = email.parser.BytesParser().parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw
            )
            for part in message.get_payload():
                name = part.get_param("name", header="content-disposition")
                call["fields"][name] = {
                    "body": part.get_payload(decode=True),
                    "type": part.get_content_type(),
                    "filename": part.get_param("filename", header="content-disposition"),
                }
        type(self).seen.append(call)
        return call

    def _answer(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self._record()
        if type(self).behaviour == "forbidden":
            return self._answer(403, {"message": "Insufficient permissions"})
        if type(self).behaviour == "immediate":
            return self._answer(
                200, {"path": "operations/abc", "done": True, "response": {"assetId": "111"}}
            )
        self._answer(200, {"path": "operations/abc"})

    do_PATCH = do_POST

    def do_GET(self) -> None:
        self._record()
        if type(self).behaviour == "moderated":
            return self._answer(
                200, {"path": "operations/abc", "done": True, "error": {"message": "rejected"}}
            )
        self._answer(
            200,
            {
                "path": "operations/abc",
                "done": True,
                "response": {"path": "assets/2205400862", "assetId": "2205400862", "revisionId": "1"},
            },
        )


@pytest.fixture
def api():
    _Api.seen = []
    _Api.behaviour = "operation"
    server = HTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Api
    server.shutdown()
    server.server_close()


@pytest.fixture
def animation(tmp_path) -> Path:
    path = tmp_path / "Run.rbxmx"
    path.write_text('<roblox version="4"><Item class="KeyframeSequence"/></roblox>')
    return path


def test_it_sends_the_two_fields_the_api_documents(api, animation):
    base, recorder = api
    result = publish(
        animation, Creator.parse("user:42"), key=KEY, base_url=base, poll_seconds=0
    )

    upload = recorder.seen[0]
    assert upload["method"] == "POST"
    assert upload["path"] == "/assets"
    assert upload["key"] == KEY, "the key rides in x-api-key, not in the URL"

    request = json.loads(upload["fields"]["request"]["body"])
    assert request["assetType"] == "Animation"
    assert request["creationContext"]["creator"] == {"userId": "42"}
    assert request["displayName"] == "Run"

    content = upload["fields"]["fileContent"]
    assert content["body"] == animation.read_bytes()
    assert content["type"] == "model/x-rbxm", "the API types a .rbxmx as an rbxm"
    assert content["filename"] == "Run.rbxmx"

    assert result.asset_id == "2205400862"
    assert result.created is True


def test_a_group_asset_names_the_group_not_the_user(api, animation):
    base, recorder = api
    publish(animation, Creator.parse("group:7"), key=KEY, base_url=base, poll_seconds=0)
    request = json.loads(recorder.seen[0]["fields"]["request"]["body"])
    assert request["creationContext"]["creator"] == {"groupId": "7"}, (
        "publishing under a group is the case that used to force the cookie path"
    )


def test_publishing_with_an_asset_id_updates_instead_of_duplicating(api, animation):
    base, recorder = api
    result = publish(
        animation,
        Creator.parse("user:42"),
        asset_id="999",
        key=KEY,
        base_url=base,
        poll_seconds=0,
    )
    call = recorder.seen[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/assets/999"
    request = json.loads(call["fields"]["request"]["body"])
    assert request["assetId"] == "999"
    assert "displayName" not in request, "displayName is a creation field only"
    assert result.created is False


def test_an_operation_that_is_already_done_is_not_polled(api, animation):
    base, recorder = api
    recorder.behaviour = "immediate"
    result = publish(
        animation, Creator.parse("user:42"), key=KEY, base_url=base, poll_seconds=0
    )
    assert result.asset_id == "111"
    assert len(recorder.seen) == 1, "there was nothing to wait for"


def test_a_refusal_says_which_permission_is_missing(api, animation):
    base, recorder = api
    recorder.behaviour = "forbidden"
    with pytest.raises(PublishError) as caught:
        publish(animation, Creator.parse("group:7"), key=KEY, base_url=base, poll_seconds=0)
    message = str(caught.value)
    assert "assets" in message and "group" in message
    assert KEY not in message, "an error message must never carry the key"


def test_an_operation_that_finishes_without_an_asset_is_not_reported_as_success(api, animation):
    base, recorder = api
    recorder.behaviour = "moderated"
    with pytest.raises(PublishError, match="without producing an asset"):
        publish(animation, Creator.parse("user:42"), key=KEY, base_url=base, poll_seconds=0)


def test_the_key_comes_from_the_environment_and_says_so_when_it_does_not(monkeypatch):
    for name in ("ROBLOX_API_KEY", "LINEN_ROBLOX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(PublishError, match="create.roblox.com"):
        api_key()
    monkeypatch.setenv("ROBLOX_API_KEY", "  from-the-env  ")
    assert api_key() == "from-the-env"


def test_the_key_is_never_a_command_line_argument():
    """The one guarantee that cannot be walked back later.

    An argument is readable by every process on the machine through `ps` and is
    written to shell history. A key that gets there has to be revoked, and
    people do not notice they need to.
    """
    from linen.cli import main

    with pytest.raises(SystemExit):
        main(["publish", "x.rbxmx", "--creator", "user:1", "--api-key", KEY])


def test_a_creator_that_is_not_a_user_or_a_group_is_rejected():
    for bad in ("42", "user:", "org:42", "user:me"):
        with pytest.raises(ValueError, match="user:ID"):
            Creator.parse(bad)


def test_the_manifest_round_trips_so_a_second_run_updates(tmp_path):
    path = tmp_path / "publish.json"
    assert load_manifest(path) == {}
    save_manifest(path, {"Run.rbxmx": "123"}, Creator.parse("group:7"))
    assert load_manifest(path) == {"Run.rbxmx": "123"}
    assert json.loads(path.read_text())["creator"] == "group:7"


def test_a_missing_file_is_caught_before_anything_is_sent(api, tmp_path):
    base, recorder = api
    with pytest.raises(PublishError, match="no such file"):
        publish(tmp_path / "gone.rbxmx", Creator.parse("user:42"), key=KEY, base_url=base)
    assert recorder.seen == []


def test_the_command_writes_a_manifest_and_reuses_it_on_the_second_run(
    api, tmp_path, monkeypatch, capsys
):
    """Two runs, one asset. Without the manifest the second run makes a copy.

    A duplicate is the worst outcome of the three: it succeeds, it prints an id,
    and it is not the id anything in the game points at.
    """
    import linen.cloud
    from linen.cli import main

    base, recorder = api
    monkeypatch.setattr(linen.cloud, "BASE_URL", base)
    monkeypatch.setattr(linen.cloud, "POLL_SECONDS", 0)
    monkeypatch.setenv("ROBLOX_API_KEY", KEY)

    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "Run.rbxmx").write_text("<roblox/>")
    manifest = tmp_path / "publish.json"

    assert main(["publish", str(folder), "--creator", "user:42", "--manifest", str(manifest)]) == 0
    assert "rbxassetid://2205400862" in capsys.readouterr().out
    assert load_manifest(manifest) == {"Run.rbxmx": "2205400862"}

    recorder.seen.clear()
    assert main(["publish", str(folder), "--creator", "user:42", "--manifest", str(manifest)]) == 0
    assert recorder.seen[0]["method"] == "PATCH", "the second run must update, not duplicate"
    assert recorder.seen[0]["path"] == "/assets/2205400862"


def test_a_failed_file_does_not_take_the_others_down_with_it(api, tmp_path, monkeypatch, capsys):
    import linen.cloud
    from linen.cli import main

    base, recorder = api
    monkeypatch.setattr(linen.cloud, "BASE_URL", base)
    monkeypatch.setattr(linen.cloud, "POLL_SECONDS", 0)
    monkeypatch.setenv("ROBLOX_API_KEY", KEY)
    recorder.behaviour = "forbidden"

    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "A.rbxmx").write_text("<roblox/>")
    (folder / "B.rbxmx").write_text("<roblox/>")

    assert main(["publish", str(folder), "--creator", "group:7"]) == 1
    errors = capsys.readouterr().err
    assert "echec A.rbxmx" in errors and "echec B.rbxmx" in errors
    assert KEY not in errors
