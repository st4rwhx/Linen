"""Free-tier language model access, with failover between providers.

Every provider here has a no-cost path, and none of them is reliable on its
own: free tiers rate-limit hard and change model names without notice.  So the
chain tries providers in order and moves on when one refuses, and the model IDs
are all overridable by environment variable rather than baked in.

The only thing a model is asked for is a :class:`~linen.generate.schema.MotionPlan`
(see :mod:`linen.generate.choreographer`), so a weaker free model costs planning
nuance, never animation quality — the poses are ours either way.

Set any of ``GEMINI_API_KEY``, ``DEEPSEEK_API_KEY``, ``MOONSHOT_API_KEY``,
``XAI_API_KEY``, ``GROQ_API_KEY`` or ``OPENROUTER_API_KEY``; override a model
with e.g. ``LINEN_GEMINI_MODEL``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT = 60.0


class ProviderError(RuntimeError):
    """A provider refused a request. Carries whether retrying elsewhere helps."""

    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


class NoProviderConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class Provider:
    """One LLM endpoint.

    ``style`` is either ``"openai"`` for the many ``/chat/completions`` clones
    or ``"gemini"`` for Google's own shape.
    """

    name: str
    env_key: str
    base_url: str
    default_model: str
    style: str = "openai"
    #: Free tier notes, surfaced in `linen providers` so the choice is informed.
    notes: str = ""

    @property
    def model(self) -> str:
        return os.environ.get(f"LINEN_{self.name.upper()}_MODEL", self.default_model)

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.env_key) or None

    @property
    def configured(self) -> bool:
        return self.api_key is not None


#: Ordered by how much free headroom they tend to offer, best first.  Model IDs
#: are defaults as of writing; providers rename models often, so override with
#: ``LINEN_<PROVIDER>_MODEL`` rather than treating these as guaranteed.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini-2.5-flash",
        style="gemini",
        notes="Indefinite free tier, no card. Best free daily quota; supports response schemas.",
    ),
    Provider(
        "groq",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        notes="Free tier, very fast. Open-weight models only.",
    ),
    Provider(
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        "openrouter/free",
        notes="Routes across whichever models are free that day. Low daily cap.",
    ),
    Provider(
        "deepseek",
        "DEEPSEEK_API_KEY",
        "https://api.deepseek.com/v1",
        "deepseek-chat",
        notes="Cheap rather than free; trial credit on signup.",
    ),
    Provider(
        "moonshot",
        "MOONSHOT_API_KEY",
        "https://api.moonshot.ai/v1",
        "kimi-k2.5",
        notes="Kimi. Free daily request allowance on the base tier.",
    ),
    Provider(
        "xai",
        "XAI_API_KEY",
        "https://api.x.ai/v1",
        "grok-4.5",
        notes="Grok. Promotional credits rather than a standing free tier.",
    ),
)

BY_NAME: dict[str, Provider] = {p.name: p for p in PROVIDERS}


def configured_providers() -> tuple[Provider, ...]:
    return tuple(p for p in PROVIDERS if p.configured)


def complete_json(
    system: str,
    user: str,
    *,
    schema: dict[str, Any] | None = None,
    providers: tuple[Provider, ...] | None = None,
    temperature: float = 0.4,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any], str]:
    """Ask the first working provider for a JSON object.

    Returns the parsed object and the name of the provider that answered.
    Raises :class:`NoProviderConfigured` when no key is set at all, and the last
    :class:`ProviderError` when every configured provider failed.
    """
    candidates = providers if providers is not None else configured_providers()
    if not candidates:
        raise NoProviderConfigured(
            "no API key found. Set one of: "
            + ", ".join(p.env_key for p in PROVIDERS)
            + " — or write the motion plan by hand and use `linen synth`."
        )

    last: Exception | None = None
    for provider in candidates:
        try:
            raw = _request(provider, system, user, schema, temperature, timeout)
            return _parse_json(provider.name, raw), provider.name
        except ProviderError as exc:
            if not exc.retryable:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = ProviderError(provider.name, f"network error: {exc}")

    raise last  # type: ignore[misc]


def _request(
    provider: Provider,
    system: str,
    user: str,
    schema: dict[str, Any] | None,
    temperature: float,
    timeout: float,
) -> str:
    if provider.style == "gemini":
        url = (
            f"{provider.base_url}/models/{provider.model}:generateContent"
            f"?key={provider.api_key}"
        )
        generation: dict[str, Any] = {
            "temperature": temperature,
            "responseMimeType": "application/json",
        }
        if schema is not None:
            generation["responseSchema"] = _gemini_schema(schema)
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = f"{provider.base_url}/chat/completions"
        payload = {
            "model": provider.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}",
        }

    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        # 401/403 mean this key will never work; there is no point retrying it,
        # but other providers in the chain still might, so it stays retryable
        # at the chain level and only the message changes.
        raise ProviderError(provider.name, f"HTTP {exc.code}: {detail}") from None

    return _extract_text(provider, body)


def _extract_text(provider: Provider, body: dict[str, Any]) -> str:
    try:
        if provider.style == "gemini":
            parts = body["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(
            provider.name, f"unexpected response shape: {json.dumps(body)[:400]}"
        ) from None


def _parse_json(provider: str, raw: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating the fenced code blocks models emit."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ProviderError(provider, f"no JSON object in response: {raw[:200]}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(provider, f"invalid JSON: {exc}") from None
    if not isinstance(parsed, dict):
        raise ProviderError(provider, f"expected an object, got {type(parsed).__name__}")
    return parsed


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip the JSON Schema keywords Gemini's subset rejects."""
    unsupported = {"additionalProperties", "$schema", "minItems", "exclusiveMinimum"}
    if isinstance(schema, dict):
        return {
            key: _gemini_schema(value)
            for key, value in schema.items()
            if key not in unsupported
        }
    if isinstance(schema, list):
        return [_gemini_schema(item) for item in schema]  # type: ignore[return-value]
    return schema
