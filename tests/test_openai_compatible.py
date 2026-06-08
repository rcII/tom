"""The OpenAI-compatible local-model client, against a mocked transport."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from tom.adapters.openai_compatible import (
    BASE_URL_ENV,
    MODEL_ENV,
    TIMEOUT_ENV,
    OpenAICompatibleClient,
)
from tom.llm import ChatMessage, LlmClient, Role

_REPLY = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hello there"}}]})


class _Transport:
    """Records the request and returns a scripted reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.url: str | None = None
        self.body: bytes | None = None
        self.timeout: float | None = None

    def __call__(self, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> str:
        self.url = url
        self.body = body
        self.timeout = timeout
        return self.reply


def _client(transport: _Transport) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="http://spark.local:8080/", model="qwen3", timeout=30.0, post=transport
    )


def test_satisfies_llm_client_protocol() -> None:
    client: LlmClient = _client(_Transport(_REPLY))
    assert client.chat([ChatMessage(role=Role.USER, content="hi")]) == "hello there"


def test_posts_to_the_chat_completions_path() -> None:
    transport = _Transport(_REPLY)
    _client(transport).chat([ChatMessage(role=Role.SYSTEM, content="be terse")])
    # Base URL's trailing slash is normalized, and the path is appended once.
    assert transport.url == "http://spark.local:8080/v1/chat/completions"
    assert transport.timeout == 30.0


def test_sends_model_and_mapped_messages() -> None:
    transport = _Transport(_REPLY)
    _client(transport).chat(
        [
            ChatMessage(role=Role.SYSTEM, content="be terse"),
            ChatMessage(role=Role.USER, content="status?"),
        ]
    )
    assert transport.body is not None
    sent = json.loads(transport.body)
    assert sent["model"] == "qwen3"
    assert sent["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "status?"},
    ]


def test_extracts_the_assistant_content() -> None:
    reply = json.dumps({"choices": [{"message": {"content": "the answer"}}]})
    answer = _client(_Transport(reply)).chat([ChatMessage(role=Role.USER, content="q")])
    assert answer == "the answer"


def test_unreachable_endpoint_fails_loud_with_no_fallback() -> None:
    def refuse(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> str:
        raise ConnectionRefusedError("connection refused")

    client = OpenAICompatibleClient(
        base_url="http://spark.local:8080", model="qwen3", timeout=5.0, post=refuse
    )
    with pytest.raises(RuntimeError, match="failed"):
        client.chat([ChatMessage(role=Role.USER, content="hi")])


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        json.dumps({"choices": []}),
        json.dumps({"choices": [{"message": {}}]}),
        json.dumps({"nope": True}),
        json.dumps({"choices": [{"message": {"content": 123}}]}),
    ],
)
def test_malformed_reply_fails_loud(reply: str) -> None:
    with pytest.raises(RuntimeError, match="tom-llm"):
        _client(_Transport(reply)).chat([ChatMessage(role=Role.USER, content="hi")])


def test_from_env_reads_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "http://spark.local:8080")
    monkeypatch.setenv(MODEL_ENV, "qwen3")
    monkeypatch.setenv(TIMEOUT_ENV, "45")
    client = OpenAICompatibleClient.from_env()
    captured: dict[str, object] = {}

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> str:
        captured["url"] = url
        captured["timeout"] = timeout
        return _REPLY

    client._post = transport
    client.chat([ChatMessage(role=Role.USER, content="hi")])
    assert captured["url"] == "http://spark.local:8080/v1/chat/completions"
    assert captured["timeout"] == 45.0


def test_from_env_unset_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BASE_URL_ENV, raising=False)
    with pytest.raises(ValueError, match="not set"):
        OpenAICompatibleClient.from_env()
