from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

from app.config.settings import settings


class LLMService:
    """Hugging Face/Ollama-backed LLM abstraction used by agents."""

    SUPPORTED_PROVIDERS = {"auto", "huggingface", "ollama"}

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        hf_token: Optional[str] = None,
        hf_model: Optional[str] = None,
        ollama_base_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        selected_provider = (provider or settings.llm_provider).strip().lower()
        self.provider = selected_provider if selected_provider in self.SUPPORTED_PROVIDERS else "auto"

        self.hf_token = hf_token if hf_token is not None else settings.hf_token
        self.hf_model = hf_model or model or settings.hf_model
        self.ollama_base_url = (ollama_base_url or settings.ollama_base_url).rstrip("/")
        self.ollama_model = ollama_model or model or settings.ollama_model
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds
        self.active_provider = self._resolve_provider()
        self.model = self._resolve_model_name()

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text using the configured provider.

        Returns an empty string when provider is unavailable so callers can fallback.
        """
        result = await self.generate_with_diagnostics(prompt, **kwargs)
        return result["output"]

    async def generate_with_diagnostics(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate text and expose provider/model/timing/error diagnostics."""
        self.active_provider = self._resolve_provider()
        self.model = self._resolve_model_name()
        started = time.perf_counter()

        if self.active_provider == "huggingface":
            output, error = await self._generate_with_huggingface(prompt, **kwargs)
        elif self.active_provider == "ollama":
            output, error = await self._generate_with_ollama(prompt, **kwargs)
        else:
            output, error = (
                "",
                "No active LLM provider. Configure Hugging Face token or Ollama endpoint/model.",
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {
            "provider": self.active_provider or "none",
            "model": self.model,
            "latency_ms": latency_ms,
            "output": output,
            "error": error,
            "response_chars": len(output),
            "ok": bool(output and not error),
        }

    def _resolve_provider(self) -> str:
        if self.provider == "huggingface":
            return "huggingface" if self.hf_token else ""
        if self.provider == "ollama":
            return "ollama" if self.ollama_base_url and self.ollama_model else ""
        if self.hf_token:
            return "huggingface"
        if self.ollama_base_url and self.ollama_model:
            return "ollama"
        return ""

    def _resolve_model_name(self) -> str:
        if self.active_provider == "huggingface":
            return self.hf_model
        if self.active_provider == "ollama":
            return self.ollama_model
        return self.hf_model

    async def _generate_with_huggingface(self, prompt: str, **kwargs: Any) -> tuple[str, str | None]:
        if not self.hf_token:
            return "", "Hugging Face token is missing."

        system_prompt = kwargs.get(
            "system_prompt",
            "You are a strict data extraction assistant that returns valid JSON only.",
        )
        payload_base: dict[str, Any] = {
            "model": kwargs.get("model", self.hf_model),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": kwargs.get("temperature", 0.0),
        }
        if kwargs.get("max_tokens") is not None:
            payload_base["max_tokens"] = kwargs.get("max_tokens")
        if kwargs.get("top_p") is not None:
            payload_base["top_p"] = kwargs.get("top_p")
        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json",
        }
        prefer_json_mode = bool(kwargs.get("json_mode", True))
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                for json_mode in ([True, False] if prefer_json_mode else [False]):
                    payload = dict(payload_base)
                    if json_mode:
                        payload["response_format"] = {"type": "json_object"}

                    response = await client.post(
                        "https://router.huggingface.co/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        response_text = exc.response.text[:400]
                        # Retry once without JSON mode when provider/model does not support response_format.
                        if (
                            json_mode
                            and exc.response.status_code == 400
                            and (
                                "response_format" in response_text
                                or "json_object" in response_text
                                or "unsupported" in response_text
                            )
                        ):
                            continue
                        hint = ""
                        if exc.response.status_code == 400 and "model_not_supported" in response_text:
                            hint = (
                                " Try GRID_APP_HF_MODEL=katanemo/Arch-Router-1.5B:hf-inference "
                                "or remove the ':hf-inference' suffix to let Hugging Face route automatically."
                            )
                        if exc.response.status_code == 410 and "model_no_longer_supported" in response_text:
                            hint = (
                                " This model/provider combination is deprecated. "
                                "Try GRID_APP_HF_MODEL=katanemo/Arch-Router-1.5B:hf-inference."
                            )
                        return "", f"Hugging Face HTTP {exc.response.status_code}: {response_text}{hint}"

                    data = response.json()
                    content = self._extract_chat_completion_content(data)
                    if not content:
                        return "", "Hugging Face response is missing message content."
                    return content, None
        except httpx.HTTPStatusError as exc:
            return "", f"Hugging Face HTTP {exc.response.status_code}: {exc.response.text[:400]}"
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            return "", f"Hugging Face request failed: {exc}"

    async def _generate_with_ollama(self, prompt: str, **kwargs: Any) -> tuple[str, str | None]:
        if not self.ollama_base_url or not self.ollama_model:
            return "", "Ollama endpoint/model is not configured."

        system_prompt = kwargs.get(
            "system_prompt",
            "You are a strict data extraction assistant that returns valid JSON only.",
        )
        options = {
            "temperature": kwargs.get("temperature", 0.0),
            "num_predict": kwargs.get("max_tokens"),
            "top_p": kwargs.get("top_p"),
        }
        options = {key: value for key, value in options.items() if value is not None}
        payload = {
            "model": kwargs.get("model", self.ollama_model),
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": options,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.ollama_base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                message = data.get("response")
                if not isinstance(message, str) or not message.strip():
                    return "", "Ollama response is missing generated text."
                return message, None
        except httpx.HTTPStatusError as exc:
            return "", f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:400]}"
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
            return "", f"Ollama request failed: {exc}"

    @staticmethod
    def _extract_chat_completion_content(payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None
        message = first_choice.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        if isinstance(content, str):
            stripped = content.strip()
            return stripped or None
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            joined = "".join(parts).strip()
            return joined or None
        return None
