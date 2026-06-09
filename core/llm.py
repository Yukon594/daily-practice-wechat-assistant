from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import requests

from config import Settings


class LLMError(RuntimeError):
    """Raised when the DeepSeek request fails."""


class DeepSeekClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def chat(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> Any:
        if not self.is_configured:
            raise LLMError("DeepSeek API key is missing. Fill config.json first.")

        payload: Dict[str, Any] = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        last_error = None
        for _ in range(2):
            try:
                response = requests.post(
                    self.settings.chat_endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.settings.request_timeout,
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"].strip()
                if not json_mode:
                    return content
                return self._parse_json_content(content)
            except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc

        raise LLMError(f"DeepSeek request failed: {last_error}")

    def _parse_json_content(self, content: str) -> Any:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```json\s*(.*?)\s*```", content, flags=re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))

        object_match = re.search(r"(\{.*\}|\[.*\])", content, flags=re.DOTALL)
        if object_match:
            return json.loads(object_match.group(1))

        raise json.JSONDecodeError("Unable to parse JSON from model output.", content, 0)
