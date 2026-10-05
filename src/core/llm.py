"""OpenAI-compatible chat client, configured via NONO_* environment variables."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_number(name: str, default: float, cast: type) -> float | int:
    """Read a numeric env var, falling back to ``default`` when unset or bad."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return cast(default)
    try:
        return cast(raw)
    except ValueError:
        return cast(default)


@dataclass(frozen=True)
class TurnChunk:
    """One piece of a streamed assistant turn.

    Attributes:
        text: Incremental visible text; concatenating every chunk gives the turn's reply.
        tool_calls: Set only on the terminal chunk: the model's tool requests as
            id/name/arguments dicts, empty when it simply finished.
    """

    text: str = ""
    tool_calls: list[dict[str, str]] | None = None


class LLM:
    """Thin OpenAI-compatible chat wrapper. Needs base url, api key, and model."""

    def __init__(self) -> None:
        load_dotenv(_project_root() / ".env")
        self.baseurl = os.getenv("NONO_BASE_URL")
        self.apikey = os.getenv("NONO_API_KEY")
        self.model = os.getenv("NONO_MODEL")
        assert self.baseurl is not None, "NONO_BASE_URL is not set"
        assert self.apikey is not None, "NONO_API_KEY is not set"
        assert self.model is not None, "NONO_MODEL is not set"
        # The SDK handles transient network errors and 5xx itself; a request
        # that stalls past the timeout fails the turn (which Nono rolls back).
        self.client = OpenAI(
            base_url=self.baseurl,
            api_key=self.apikey,
            timeout=_env_number("NONO_TIMEOUT", 60.0, float),
            max_retries=_env_number("NONO_MAX_RETRIES", 2, int),
        )

    def chat(self, prompt: str | list[str]) -> str:
        """One-shot helper: turn a prompt (or prompt parts) into a reply."""
        return self.complete(self._to_messages(prompt))

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return the assistant reply for ``messages``."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        content = response.choices[0].message.content
        return content or ""

    def stream(self, messages: list[dict[str, Any]]) -> Iterator[str]:
        """Yield the assistant reply piece by piece as it arrives."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content

    def stream_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[TurnChunk]:
        """Stream one assistant turn, accumulating tool calls on the side.

        Args:
            messages: The conversation so far, OpenAI chat format.
            tools: Function-calling schemas the model may request, or None.

        Yields:
            Text chunks as they arrive, then one terminal chunk whose
            ``tool_calls`` holds the (possibly empty) accumulated requests.
        """
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools
        response = self.client.chat.completions.create(**kwargs)
        pending: dict[int, dict[str, str]] = {}
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield TurnChunk(text=delta.content)
            for call in delta.tool_calls or []:
                # Fragments are keyed by index: id and name arrive first,
                # arguments trickle in afterwards.
                slot = pending.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
                if call.id:
                    slot["id"] = call.id
                if call.function:
                    if call.function.name:
                        slot["name"] += call.function.name
                    if call.function.arguments:
                        slot["arguments"] += call.function.arguments
        yield TurnChunk(tool_calls=[pending[i] for i in sorted(pending)])

    def _to_messages(self, prompt: str | list[str]) -> list[dict[str, Any]]:
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]
        return [{"role": "user", "content": item} for item in prompt]
