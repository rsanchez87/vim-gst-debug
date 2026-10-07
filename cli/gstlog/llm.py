"""Provider-agnostic LLM access.

One adapter speaks the OpenAI-compatible chat protocol, which covers DeepSeek,
OpenAI, Ollama, vLLM and most company gateways. Adding another protocol means
adding another Provider subclass; nothing else in the tool changes.

The API key is read only from an environment variable, never from argv.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Preset:
    base_url: str
    model: Optional[str]
    key_env: Optional[str]
    key_required: bool = True


PRESETS = {
    # Model names change often: override with --model / GSTLOG_LLM_MODEL.
    "deepseek": Preset("https://api.deepseek.com", "deepseek-chat", "DEEPSEEK_API_KEY"),
    "openai": Preset("https://api.openai.com/v1", None, "OPENAI_API_KEY"),
    "ollama": Preset("http://localhost:11434/v1", None, None),
    "custom": Preset("", None, "GSTLOG_LLM_API_KEY", key_required=False),
}


class Provider:
    name = "base"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def request_preview(self, system: str, user: str) -> dict:  # pragma: no cover
        raise NotImplementedError


class OpenAICompatible(Provider):
    def __init__(self, base_url: str, model: str, api_key: Optional[str] = None,
                 timeout: float = 60.0, json_mode: bool = True, max_tokens: int = 800):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.json_mode = json_mode
        self.max_tokens = max_tokens
        self.name = f"{model}@{self.base_url}"

    def _payload(self, system: str, user: str) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def request_preview(self, system: str, user: str) -> dict:
        return {"url": f"{self.base_url}/chat/completions", "body": self._payload(system, user)}

    def complete(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(self._payload(system, user)).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise LLMError(f"HTTP {e.code} from provider: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f"cannot reach provider: {e}") from None
        except json.JSONDecodeError:
            raise LLMError("provider did not return JSON") from None
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected provider response shape") from None
        if not content or not content.strip():
            raise LLMError("provider returned an empty answer")
        return content


def build_provider(preset: Optional[str] = None, base_url: Optional[str] = None,
                   model: Optional[str] = None, key_env: Optional[str] = None,
                   json_mode: bool = True, env=os.environ) -> Optional[OpenAICompatible]:
    """Return a configured provider, or None when nothing is configured."""
    preset = preset or env.get("GSTLOG_LLM_PRESET") or ("deepseek" if env.get("DEEPSEEK_API_KEY") else None)
    if preset is None and not (base_url or env.get("GSTLOG_LLM_BASE_URL")):
        return None
    p = PRESETS.get(preset or "custom")
    if p is None:
        raise LLMError(f"unknown preset {preset!r}; choose from {', '.join(PRESETS)}")
    base = base_url or env.get("GSTLOG_LLM_BASE_URL") or p.base_url
    mdl = model or env.get("GSTLOG_LLM_MODEL") or p.model
    if not base or not mdl:
        raise LLMError("base URL and model are required (use --base-url/--model or GSTLOG_LLM_*)")
    env_name = key_env or p.key_env
    key = env.get(env_name) if env_name else None
    if env_name and not key and (p.key_required or key_env):
        raise LLMError(f"environment variable {env_name} is not set")
    return OpenAICompatible(base, mdl, key, json_mode=json_mode)
