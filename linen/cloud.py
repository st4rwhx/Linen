"""Publish an animation to Roblox through Open Cloud, and get a real asset id.

Everything else in this project stops at a file. A file is not what a running
game plays: a game plays ``rbxassetid://`` numbers, and getting one has
historically meant opening the Animation Editor and pressing Publish, once per
animation, by hand. That is the step this closes.

``Animation`` is a first-class asset type of the Assets API and it accepts
``.rbxmx`` — the exact format Linen writes — so nothing has to be repackaged.
The creator can be a user or a group, which is the case that used to force
people onto the old cookie-based endpoints: it does not any more.

Roblox warns that a file Studio did not write may not process. It does: a
generated ``.rbxmx`` went up through this and became asset 121632245238820,
which plays on a rig. That is the one thing here no test can hold.

**The key never travels through an argument.** It is read from the environment
and from nowhere else, it is never printed, and it is stripped out of error
text before anything is raised. A key that reaches ``argv`` is visible to every
other process on the machine through ``ps`` and lands in the shell history; a
key that reaches a traceback lands in whatever collects logs. Neither is
recoverable after the fact, so neither is allowed to happen.

Why an API key rather than a ``.ROBLOSECURITY`` cookie, which the older tools
ask for: the key is scoped to assets and revocable in one click, while the
cookie is the whole account — Robux, Limiteds, email — is invalidated whenever
the session rotates, and is what gets accounts flagged for automated traffic.
The cookie is not more capable here. It is only older.
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

#: Where the key is read from. Nowhere else, and never an argument.
KEY_VARIABLES = ("ROBLOX_API_KEY", "LINEN_ROBLOX_API_KEY")

BASE_URL = "https://apis.roblox.com/assets/v1"

#: What Roblox calls the format we write. `.rbxmx` is XML, but the API types it
#: by asset rather than by encoding and wants this for both `.rbxm` and `.rbxmx`.
RBXM_MIME = "model/x-rbxm"

#: A create returns a long-running operation, not an asset. Moderation runs in
#: it, so it is normal for this to take a few seconds.
POLL_SECONDS = 1.5
POLL_ATTEMPTS = 40

#: Publishing a folder is a burst, and a burst is what the rate limiter is for.
#: Giving up on the eleventh file of seventeen would leave the job half done and
#: the manifest half written, so a 429 waits and tries again instead. Roblox
#: usually names the wait in `Retry-After`; where it does not, this doubles.
RETRY_ATTEMPTS = 4
RETRY_SECONDS = 4.0


class PublishError(RuntimeError):
    """A publish that did not happen, said in terms of what to do about it."""


@dataclass(frozen=True)
class Creator:
    """Who owns the asset once it exists."""

    kind: str  # "user" or "group"
    identifier: str

    @classmethod
    def parse(cls, text: str) -> Creator:
        kind, _, identifier = text.partition(":")
        kind = kind.strip().lower()
        identifier = identifier.strip()
        if kind not in ("user", "group") or not identifier.isdigit():
            raise ValueError(
                f"--creator expects 'user:ID' or 'group:ID', not {text!r}. The id "
                f"is the number in your profile or group URL."
            )
        return cls(kind, identifier)

    def payload(self) -> dict:
        # A group asset carries `groupId`; a personal one carries `userId`.
        # Publishing to a group needs the key's owner to hold that permission in
        # the group, which the API checks rather than this.
        return {"creator": {f"{self.kind}Id": self.identifier}}

    def __str__(self) -> str:
        return f"{self.kind}:{self.identifier}"


@dataclass(frozen=True)
class Published:
    """What came back: the asset, and whether it was new."""

    path: Path
    asset_id: str
    revision: str | None
    created: bool

    def line(self) -> str:
        what = "cree" if self.created else "mis a jour"
        revision = f", revision {self.revision}" if self.revision else ""
        return f"{self.path.name}: rbxassetid://{self.asset_id} ({what}{revision})"


def api_key() -> str:
    """The key, from the environment. Absent, this says how to set one."""
    for name in KEY_VARIABLES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise PublishError(
        f"no API key. Create one at create.roblox.com/dashboard/credentials with "
        f"the 'assets' permission (Read and Write), then export it as "
        f"{KEY_VARIABLES[0]}. Do not pass it as an argument — arguments are "
        f"visible to every process on the machine and are kept in shell history."
    )


def publish(
    path: Path,
    creator: Creator,
    *,
    name: str | None = None,
    description: str = "",
    asset_id: str | None = None,
    asset_type: str = "Animation",
    key: str | None = None,
    base_url: str | None = None,
    poll_seconds: float = POLL_SECONDS,
    retry_seconds: float = RETRY_SECONDS,
) -> Published:
    """Upload one file, wait for Roblox to finish with it, return its asset id.

    Passing ``asset_id`` updates that asset in place, which keeps every
    ``Animation`` instance in the game pointing at it. Without one a new asset
    is created and the id has to be wired up once.
    """
    path = Path(path)
    if not path.is_file():
        raise PublishError(f"{path}: no such file")
    key = key or api_key()
    # Resolved here rather than in the signature so the default is the module's
    # current value: the tests point it at a stand-in, and a default bound at
    # import time would quietly ignore that and reach for the real Roblox.
    base_url = base_url or BASE_URL

    request = {
        "assetType": asset_type,
        "creationContext": creator.payload(),
    }
    if asset_id:
        request["assetId"] = asset_id
        url = f"{base_url}/assets/{asset_id}"
        method = "PATCH"
    else:
        # displayName and description are only accepted on creation; sending
        # them on an update is what the separate metadata call is for.
        request["displayName"] = name or path.stem
        request["description"] = description
        url = f"{base_url}/assets"
        method = "POST"

    body, content_type = _multipart(request, path)
    answer = _call(url, method, key, body, content_type, retry_seconds=retry_seconds)

    operation = answer.get("path", "")
    if answer.get("done") and "response" in answer:
        finished = answer["response"]
    elif operation:
        finished = _await_operation(operation, key, base_url, poll_seconds, retry_seconds)
    else:
        raise PublishError(
            f"{path.name}: Roblox accepted the upload but named no operation to "
            f"follow. Raw answer: {json.dumps(answer)[:400]}"
        )

    got = str(finished.get("assetId") or "")
    if not got:
        raise PublishError(f"{path.name}: the operation finished with no asset id")
    return Published(path, got, finished.get("revisionId"), created=asset_id is None)


def _await_operation(
    operation: str, key: str, base_url: str, poll_seconds: float, retry_seconds: float
) -> dict:
    """Wait for the asset to exist. Moderation runs inside this."""
    identifier = operation.rsplit("/", 1)[-1]
    url = f"{base_url}/operations/{identifier}"
    for _ in range(POLL_ATTEMPTS):
        answer = _call(url, "GET", key, None, None, retry_seconds=retry_seconds)
        if answer.get("done"):
            if "response" in answer:
                return answer["response"]
            raise PublishError(
                f"the upload finished without producing an asset: "
                f"{json.dumps(answer.get('error', answer))[:400]}"
            )
        time.sleep(poll_seconds)
    raise PublishError(
        f"the upload was accepted but was still not finished after "
        f"{POLL_ATTEMPTS * poll_seconds:.0f}s. It may still land — check "
        f"create.roblox.com/dashboard/creations before uploading it again."
    )


def _multipart(request: dict, path: Path) -> tuple[bytes, str]:
    """The two-field form the Assets API takes: `request` JSON, then the file."""
    boundary = f"----linen{uuid.uuid4().hex}"
    marker = f"--{boundary}".encode()
    mime = RBXM_MIME
    if path.suffix.lower() not in (".rbxm", ".rbxmx"):
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    parts = [
        marker,
        b'Content-Disposition: form-data; name="request"',
        b"Content-Type: application/json",
        b"",
        json.dumps(request).encode(),
        marker,
        f'Content-Disposition: form-data; name="fileContent"; filename="{path.name}"'.encode(),
        f"Content-Type: {mime}".encode(),
        b"",
        path.read_bytes(),
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(parts), f"multipart/form-data; boundary={boundary}"


def _call(
    url: str,
    method: str,
    key: str,
    body: bytes | None,
    content_type: str | None,
    *,
    retry_seconds: float = RETRY_SECONDS,
) -> dict:
    headers = {"x-api-key": key}
    if content_type:
        headers["Content-Type"] = content_type

    wait = retry_seconds
    for attempt in range(RETRY_ATTEMPTS):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as answer:
                return json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as exc:
            # 429 is the rate limiter and 5xx is Roblox having a moment. Both
            # pass. Everything else is about this request and will not.
            if exc.code != 429 and exc.code < 500:
                raise PublishError(_explain(exc, key)) from None
            if attempt == RETRY_ATTEMPTS - 1:
                raise PublishError(_explain(exc, key)) from None
            time.sleep(_retry_after(exc, wait))
            wait *= 2
        except urllib.error.URLError as exc:
            raise PublishError(f"could not reach {url}: {_redact(str(exc.reason), key)}") from None
        except json.JSONDecodeError as exc:
            raise PublishError(f"{url} answered something that is not JSON: {exc}") from None
    raise PublishError(f"{url}: gave up after {RETRY_ATTEMPTS} attempts")


def _retry_after(error: urllib.error.HTTPError, fallback: float) -> float:
    """How long Roblox asked us to wait, when it says so."""
    told = (error.headers or {}).get("Retry-After", "")
    try:
        # Capped: a header saying "come back in an hour" should surface as a
        # failure to read, not as a command line that appears to have hung.
        return min(max(float(told), 0.0), 60.0)
    except (TypeError, ValueError):
        return fallback


def _explain(error: urllib.error.HTTPError, key: str) -> str:
    """Turn an HTTP status into the thing to go and fix."""
    try:
        detail = _redact(error.read().decode("utf-8", "replace")[:400], key)
    except (OSError, ValueError):  # the body is optional and may already be spent
        detail = ""

    hint = {
        401: (
            "the key was rejected. Check it is the key itself and not its name, "
            "and that it has not expired."
        ),
        403: (
            "the key is valid but not allowed to do this. Add the 'assets' "
            "permission with Read and Write, and if you are publishing to a "
            "group, check the key's owner holds that permission in the group. "
            "An IP allowlist on the key also lands here when your address moved."
        ),
        400: (
            "Roblox refused the file or the request. A generated .rbxmx can hit "
            "this — Roblox warns that files not written by Studio may not "
            "process. If it is the file, importing it in Studio and re-saving is "
            "the fallback."
        ),
        413: "the file is over the 20 MB per-call limit.",
        429: "too many uploads too quickly. Wait a moment and run it again.",
    }.get(error.code, "")
    return f"HTTP {error.code} {error.reason}. {hint} {detail}".strip()


def _redact(text: str, key: str) -> str:
    """Never let the key back out through an error message."""
    return text.replace(key, "<api-key>") if key else text


def load_manifest(path: Path) -> dict[str, str]:
    """Filename -> asset id, so a second run updates instead of duplicating.

    Without this, publishing twice makes two assets and the second one is the
    one nothing in the game points at.
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    assets = data.get("assets", data)
    return {str(k): str(v) for k, v in assets.items()}


def save_manifest(path: Path, assets: dict[str, str], creator: Creator) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"creator": str(creator), "assets": assets}, indent=2, sort_keys=True) + "\n"
    )
