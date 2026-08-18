from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
        self.client = OpenAI(base_url=self.baseurl, api_key=self.apikey)

    def chat(self, prompt: str | list[str]) -> str:
        return self.complete(self._to_messages(prompt))

    def complete(self, messages: list[dict[str, Any]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        content = response.choices[0].message.content
        return content or ""

    def _to_messages(self, prompt: str | list[str]) -> list[dict[str, Any]]:
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]
        return [{"role": "user", "content": item} for item in prompt]
