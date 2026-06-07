"""The sanctioned LLM surface.

Anything the framework asks a model is asked here, through one seam, so the
sovereignty rule has a single place to hold: the model is local, and the unit
that calls it is locked down at the OS level to reach only the local endpoint.
This module is the interface; the concrete client that posts to the
OpenAI-compatible endpoint — and the egress lockdown around it — lands with the
wiring increment.

The interface is deliberately generic (chat messages in, text out) so it targets
any OpenAI-compatible server — llama.cpp today, vLLM or others later — with no
code change, only a different base URL.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


class LlmClient(Protocol):
    """A chat completion over a local, OpenAI-compatible model."""

    def chat(self, messages: Sequence[ChatMessage]) -> str: ...
