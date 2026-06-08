"""The local model, over an OpenAI-compatible endpoint.

This is the concrete :class:`~tom.llm.LlmClient`: it POSTs chat completions to a
configured ``/v1/chat/completions`` endpoint — llama.cpp on the Spark today, any
OpenAI-compatible server tomorrow, chosen by base URL alone.

Two sovereignty properties hold here at the code level:

- **One configured endpoint, no fallback.** The client talks only to
  ``TOM_LLM_BASE_URL``. If that endpoint is unreachable or errors, the call fails
  loud — it never silently degrades, and there is no cloud path to fall back to.
- **No cloud SDK.** The transport is the standard library; nothing here imports a
  hosted-model client, so the CI no-cloud-import grep stays clean.

The OS-level egress lockdown that makes a cloud call *impossible* (the systemd
unit pinned to the Spark's address, with the runtime eBPF-active self-check) is
the deployment half of the sovereignty story — wired with the live entrypoint,
not here. This half is the no-fallback client; that half is the cage around it.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping, Sequence

from tom.config import require_env
from tom.llm import ChatMessage

#: Posts a request body to a URL with a timeout and returns the response text.
#: The seam that keeps the client testable without a live endpoint.
HttpPost = Callable[[str, bytes, Mapping[str, str], float], str]

_CHAT_PATH = "/v1/chat/completions"
_JSON_HEADERS: Mapping[str, str] = {"Content-Type": "application/json"}

BASE_URL_ENV = "TOM_LLM_BASE_URL"
MODEL_ENV = "TOM_LLM_MODEL"
TIMEOUT_ENV = "TOM_LLM_TIMEOUT_SECONDS"


def _urllib_post(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> str:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw: bytes = response.read()
    return raw.decode("utf-8")


class OpenAICompatibleClient:
    """An :class:`LlmClient` over an OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float,
        post: HttpPost = _urllib_post,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._post = post

    @classmethod
    def from_env(cls) -> OpenAICompatibleClient:
        """Build from ``TOM_LLM_BASE_URL`` / ``TOM_LLM_MODEL`` / ``TOM_LLM_TIMEOUT_SECONDS``."""
        return cls(
            base_url=require_env(BASE_URL_ENV),
            model=require_env(MODEL_ENV),
            timeout=float(require_env(TIMEOUT_ENV)),
        )

    def chat(self, messages: Sequence[ChatMessage]) -> str:
        url = f"{self._base_url}{_CHAT_PATH}"
        body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            }
        ).encode("utf-8")
        try:
            raw = self._post(url, body, _JSON_HEADERS, self._timeout)
        except OSError as exc:
            # Any transport failure (urllib raises URLError/HTTPError, both OSError
            # subclasses) is fail-loud — never a silent degrade, and there is no
            # cloud endpoint to fall back to.
            raise RuntimeError(f"tom-llm request to {url} failed") from exc
        return _content_of(raw, url)


def _content_of(raw: str, url: str) -> str:
    """Pull the assistant message out of an OpenAI-compatible reply, fail-loud."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tom-llm at {url} returned non-JSON") from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"tom-llm at {url} returned no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise RuntimeError(f"tom-llm at {url} returned no message content")
    return content
