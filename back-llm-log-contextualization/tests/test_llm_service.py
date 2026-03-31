import asyncio

from app.services.llm_service import LLMService


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _patch_async_client(monkeypatch, calls: list[dict], payload: dict) -> None:
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN202
            return False

        async def post(self, url: str, headers=None, json=None):  # noqa: ANN001, ANN202
            calls.append({"url": url, "headers": headers, "json": json})
            return _FakeResponse(payload)

    monkeypatch.setattr("app.services.llm_service.httpx.AsyncClient", _FakeAsyncClient)


def test_llm_service_returns_empty_when_provider_unavailable() -> None:
    service = LLMService(provider="huggingface", hf_token="")
    result = asyncio.run(service.generate("hello"))
    assert result == ""


def test_llm_service_calls_huggingface(monkeypatch) -> None:
    calls: list[dict] = []
    _patch_async_client(
        monkeypatch,
        calls,
        {"choices": [{"message": {"content": "hf-ok"}}]},
    )
    service = LLMService(
        provider="huggingface",
        hf_token="hf-secret",
        hf_model="Qwen/Qwen2.5-7B-Instruct",
    )
    result = asyncio.run(service.generate("hello", system_prompt="sys", temperature=0.15))

    assert result == "hf-ok"
    assert calls[0]["url"] == "https://router.huggingface.co/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer hf-secret"
    assert calls[0]["json"]["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert calls[0]["json"]["messages"][0]["content"] == "sys"


def test_llm_service_calls_ollama(monkeypatch) -> None:
    calls: list[dict] = []
    _patch_async_client(
        monkeypatch,
        calls,
        {"response": "ollama-ok"},
    )
    service = LLMService(
        provider="ollama",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2:1b",
    )
    result = asyncio.run(service.generate("hello", system_prompt="sys", temperature=0.1))

    assert result == "ollama-ok"
    assert calls[0]["url"] == "http://localhost:11434/api/generate"
    assert calls[0]["json"]["model"] == "llama3.2:1b"
    assert calls[0]["json"]["system"] == "sys"
    assert calls[0]["json"]["prompt"] == "hello"


def test_llm_service_auto_prefers_huggingface_when_token_present(monkeypatch) -> None:
    calls: list[dict] = []
    _patch_async_client(
        monkeypatch,
        calls,
        {"choices": [{"message": {"content": "hf-auto-priority"}}]},
    )
    service = LLMService(
        provider="auto",
        hf_token="hf-secret",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2:1b",
    )
    result = asyncio.run(service.generate("hello"))

    assert result == "hf-auto-priority"
    assert calls[0]["url"] == "https://router.huggingface.co/v1/chat/completions"


def test_llm_service_auto_falls_back_to_ollama_when_no_hf_token(monkeypatch) -> None:
    calls: list[dict] = []
    _patch_async_client(
        monkeypatch,
        calls,
        {"response": "ollama-auto"},
    )
    service = LLMService(
        provider="auto",
        hf_token="",
        ollama_base_url="http://localhost:11434",
        ollama_model="llama3.2:1b",
    )
    result = asyncio.run(service.generate("hello"))

    assert result == "ollama-auto"
    assert calls[0]["url"] == "http://localhost:11434/api/generate"
